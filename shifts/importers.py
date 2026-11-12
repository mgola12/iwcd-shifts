"""CSV importers with dry-run. parse_* never writes; commit_* writes."""
import csv
import datetime as dt
import io
from collections import defaultdict

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction

from .models import Assignment, Eligibility, Role, ShiftImport, User, audit
from .services import closed_days

TRUE = {"yes", "y", "true", "1", "x"}
FALSE = {"no", "n", "false", "0", ""}


def _reader(text):
    text = text.lstrip("﻿")
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in rows]


def _email(value):
    value = (value or "").strip().lower()
    try:
        validate_email(value)
        return value
    except ValidationError:
        return None


def _split_name(name):
    parts = (name or "").split()
    if not parts:
        return "", ""
    return " ".join(parts[:-1]) if len(parts) > 1 else parts[0], parts[-1] if len(parts) > 1 else ""


def _get_or_create_user(email, name=""):
    user = User.objects.filter(email__iexact=email).first()
    if user:
        if name and not (user.first_name or user.last_name or user.display_name):
            user.first_name, user.last_name = _split_name(name)
            user.save(update_fields=["first_name", "last_name"])
        return user, False
    first, last = _split_name(name)
    return User.objects.create_user(email=email, first_name=first, last_name=last), True


# --------------------------------------------------------------------------- eligibility
def parse_eligibility(text):
    """Columns: email, role, eligible, note [, name, confirmed_on]."""
    rows, errors = [], []
    roles = {}
    for r in Role.objects.filter(self_service=True):
        roles.setdefault(r.code.upper(), []).append(r)
    for i, raw in enumerate(_reader(text), start=2):
        email = _email(raw.get("email"))
        code = (raw.get("role") or "").upper()
        elig_txt = (raw.get("eligible") or "yes").lower()
        if not email:
            errors.append(f"Line {i}: invalid email '{raw.get('email', '')}'")
            continue
        if code not in roles:
            errors.append(f"Line {i}: unknown role '{code}' (expected one of {', '.join(sorted(roles))})")
            continue
        if len(roles[code]) > 1:
            errors.append(f"Line {i}: role code '{code}' is ambiguous (several phases)")
            continue
        if elig_txt not in TRUE | FALSE:
            errors.append(f"Line {i}: eligible must be yes/no, got '{elig_txt}'")
            continue
        confirmed = None
        if raw.get("confirmed_on"):
            try:
                confirmed = dt.date.fromisoformat(raw["confirmed_on"])
            except ValueError:
                errors.append(f"Line {i}: confirmed_on must be YYYY-MM-DD")
                continue
        role = roles[code][0]
        user = User.objects.filter(email__iexact=email).first()
        existing = Eligibility.objects.filter(user=user, role=role).first() if user else None
        rows.append({
            "line": i, "email": email, "name": raw.get("name", ""), "role": role,
            "eligible": elig_txt in TRUE, "note": raw.get("note", ""), "confirmed_on": confirmed,
            "action": "new user" if not user else ("update" if existing else "add"),
        })
    return rows, errors


def commit_eligibility(rows, actor, file_name):
    with transaction.atomic():
        for r in rows:
            user, _ = _get_or_create_user(r["email"], r["name"])
            Eligibility.objects.update_or_create(
                user=user, role=r["role"],
                defaults={"eligible": r["eligible"], "note": r["note"], "confirmed_on": r["confirmed_on"]},
            )
            audit(actor, "eligibility_set", subject_user=user, role=r["role"],
                  note=f"{'eligible' if r['eligible'] else 'not eligible'} {r['note']}".strip())
        ShiftImport.objects.create(admin=actor, kind="eligibility", file_name=file_name, rows_loaded=len(rows))
        audit(actor, "import_run", note=f"eligibility {file_name}: {len(rows)} rows")
    return len(rows)


# --------------------------------------------------------------------------- shifters
def parse_shifters(text):
    """Columns: date, name, email, note. Dates YYYY-MM-DD (JST)."""
    rows, errors, warnings = [], [], []
    shifter_roles = list(Role.objects.filter(code=Role.SHIFTER).select_related("phase"))
    by_date = defaultdict(list)
    for i, raw in enumerate(_reader(text), start=2):
        try:
            d = dt.date.fromisoformat(raw.get("date", ""))
        except ValueError:
            errors.append(f"Line {i}: bad date '{raw.get('date', '')}' (YYYY-MM-DD)")
            continue
        email = _email(raw.get("email"))
        if not email:
            errors.append(f"Line {i}: invalid email '{raw.get('email', '')}'")
            continue
        role = next((r for r in shifter_roles if r.phase.contains(d)), None)
        if role is None:
            errors.append(f"Line {i}: {d} is not inside any phase with a SHIFTER role")
            continue
        by_date[d].append({"line": i, "date": d, "email": email, "name": raw.get("name", ""),
                           "note": raw.get("note", ""), "role": role})
    if by_date:
        closed = closed_days(min(by_date), max(by_date))
    for d in sorted(by_date):
        items = by_date[d]
        if d.weekday() >= 5 or d in closed:
            warnings.append(f"{d}: not a working day ({'weekend' if d.weekday() >= 5 else closed[d]}); loaded anyway")
        seen, keep = set(), []
        for it in items:
            if it["email"] in seen:
                warnings.append(f"Line {it['line']}: duplicate {it['email']} on {d}; ignored")
                continue
            seen.add(it["email"])
            keep.append(it)
        limit = keep[0]["role"].slots_per_day if keep else 0
        if len(keep) > limit:
            for it in keep[limit:]:
                warnings.append(f"Line {it['line']}: more than {limit} shifters on {d}; {it['email']} ignored")
            keep = keep[:limit]
        rows.extend(keep)
    return rows, errors, warnings


def commit_shifters(rows, actor, file_name):
    """Replace all imported shifter assignments in the file's date range."""
    if not rows:
        return 0
    start, end = min(r["date"] for r in rows), max(r["date"] for r in rows)
    with transaction.atomic():
        removed, _ = Assignment.objects.filter(
            role__code=Role.SHIFTER, source=Assignment.SOURCE_IMPORTED, date__range=(start, end)
        ).delete()
        for r in rows:
            user, _ = _get_or_create_user(r["email"], r["name"])
            Assignment.objects.update_or_create(
                role=r["role"], date=r["date"], user=user,
                defaults={"source": Assignment.SOURCE_IMPORTED, "note": r["note"], "created_by": actor},
            )
        ShiftImport.objects.create(admin=actor, kind="shifters", file_name=file_name, rows_loaded=len(rows),
                                   date_range_start=start, date_range_end=end)
        audit(actor, "import_run",
              note=f"shifters {file_name}: {len(rows)} rows, {start}..{end}, replaced {removed}")
    return len(rows)
