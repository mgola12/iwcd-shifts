import csv
import datetime as dt
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.cache import cache
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import importers, notify, services as S
from .forms import (AssignRangeForm, AvailabilityRangeForm, CsvUploadForm, EligibilityAddForm,
                    EmailLoginForm, UnassignRangeForm)
from .models import Assignment, Availability, Eligibility, Phase, Role, User, audit

MAGIC_SALT = "iwcd-shifts.magic-link"


# --------------------------------------------------------------------------- helpers
def coordinator_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            return HttpResponseForbidden("Coordinator access only.")
        return view(request, *args, **kwargs)
    return wrapper


def _back(request, default):
    nxt = request.POST.get("next") or request.GET.get("next")
    if nxt and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}):
        return redirect(nxt)
    return redirect(default)


def _default_month():
    t = S.today()
    first = Phase.objects.filter(subsystem__active=True).order_by("start_date").first()
    if first and t < first.start_date:
        return first.start_date.replace(day=1)
    return t.replace(day=1)


def _month_ctx(request, default=None):
    first = S.parse_month(request.GET.get("m"), default or _default_month())
    start, end = S.month_bounds(first.year, first.month)
    return first, start, end, {
        "month": first, "prev_m": f"{S.shift_month(first, -1):%Y-%m}",
        "next_m": f"{S.shift_month(first, 1):%Y-%m}", "this_m": f"{first:%Y-%m}",
    }


# --------------------------------------------------------------------------- auth
def home(request):
    if request.user.is_authenticated:
        return redirect("calendar")
    return render(request, "shifts/login.html", {
        "form": EmailLoginForm(), "next": request.GET.get("next", ""),
    })


@require_POST
def email_login(request):
    if not settings.MAGIC_LINK_ENABLED:
        raise Http404
    form = EmailLoginForm(request.POST)
    if form.is_valid():
        email = form.cleaned_data["email"].lower()
        key = f"magic:{email}"
        if cache.get(key, 0) < 5:
            cache.set(key, cache.get(key, 0) + 1, 3600)
            user = User.objects.filter(email__iexact=email, is_active=True).first()
            if user:
                token = signing.dumps(
                    {"u": user.pk, "l": user.last_login.isoformat() if user.last_login else ""},
                    salt=MAGIC_SALT,
                )
                notify.magic_link(user, settings.BASE_URL + reverse("magic", args=[token]))
        messages.info(request, "If this address is registered in the shift tool, a sign-in link is on its way. "
                               "Collaborators without an entry should use Hyper-K SSO.")
    else:
        messages.error(request, "Please enter a valid email address.")
    return redirect("home")


def magic(request, token):
    if not settings.MAGIC_LINK_ENABLED:
        raise Http404
    try:
        data = signing.loads(token, salt=MAGIC_SALT, max_age=settings.MAGIC_LINK_MAX_AGE)
        user = User.objects.get(pk=data["u"], is_active=True)
        if (user.last_login.isoformat() if user.last_login else "") != data["l"]:
            raise signing.BadSignature("already used")
    except (signing.BadSignature, signing.SignatureExpired, User.DoesNotExist, KeyError):
        messages.error(request, "This sign-in link is invalid, expired or already used. Request a new one.")
        return redirect("home")
    if request.method == "POST":  # explicit click, so mail scanners don't consume the link
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        audit(user, "login", subject_user=user, note="email link")
        return redirect("calendar")
    return render(request, "shifts/magic_confirm.html", {"login_user": user})


@require_POST
def logout_view(request):
    logout(request)
    return redirect("home")


# --------------------------------------------------------------------------- calendar
@login_required
def calendar_view(request):
    first, start, end, ctx = _month_ctx(request)
    roles = list(S.roles_in(start, end))
    cover = S.coverage(roles, start, end)
    closed = S.closed_days(start, end)
    phases = list(S.phases_in(start, end))
    weeks = []
    for week in S.month_weeks(first):
        row = []
        for d in week:
            if d is None:
                row.append(None)
                continue
            entries = [cover[(r.id, d)] for r in roles if (r.id, d) in cover]
            row.append({
                "date": d, "closed": closed.get(d), "entries": entries,
                "phase": next((p for p in phases if p.contains(d)), None), "today": d == S.today(),
            })
        weeks.append(row)
    ctx.update(weeks=weeks, phases=phases, roles=roles)
    return render(request, "shifts/calendar.html", ctx)


@login_required
def day_view(request, day):
    try:
        d = dt.date.fromisoformat(day)
    except ValueError:
        raise Http404
    roles = list(S.roles_in(d, d))
    cover = S.coverage(roles, d, d)
    entries = [cover[(r.id, d)] for r in roles if (r.id, d) in cover]
    return render(request, "shifts/day.html", {
        "day": d, "entries": entries, "closed": S.closed_days(d, d).get(d),
        "phase": S.phases_in(d, d).first(),
        "prev_day": d - dt.timedelta(days=3 if d.weekday() == 0 else 1),
        "next_day": d + dt.timedelta(days=3 if d.weekday() == 4 else 1),
    })


@login_required
def print_month(request, ym):
    first = S.parse_month(ym)
    if not first:
        raise Http404
    start, end = S.month_bounds(first.year, first.month)
    roles = list(S.roles_in(start, end))
    cover = S.coverage(roles, start, end)
    days = S.working_days(start, end)
    rows = [{"date": d, "cells": [cover.get((r.id, d)) for r in roles]} for d in days]
    return render(request, "shifts/print.html", {"month": first, "roles": roles, "rows": rows,
                                                 "phases": S.phases_in(start, end)})


# --------------------------------------------------------------------------- availability
@login_required
def availability_view(request):
    roles = list(S.eligible_roles(request.user))
    if not roles:
        return render(request, "shifts/availability.html", {"roles": []})
    role = next((r for r in roles if str(r.id) == request.GET.get("role")), roles[0])
    default = max(role.phase.start_date, S.today()).replace(day=1)
    if default > role.phase.end_date:
        default = role.phase.start_date.replace(day=1)
    first, start, end, ctx = _month_ctx(request, default)
    wd = set(S.role_working_days(role, start, end))
    mine = {a.date: a for a in Availability.objects.filter(user=request.user, role=role, date__range=(start, end))}
    assigned = set(Assignment.objects.filter(user=request.user, role=role, date__range=(start, end))
                   .values_list("date", flat=True))
    closed = S.closed_days(start, end)
    weeks = [[None if d is None else {
        "date": d, "active": d in wd, "av": mine.get(d), "assigned": d in assigned, "closed": closed.get(d),
    } for d in week] for week in S.month_weeks(first)]
    total = Availability.objects.filter(user=request.user, role=role).count()
    ctx.update(roles=roles, role=role, weeks=weeks, total=total,
               form=AvailabilityRangeForm(roles=Role.objects.filter(pk=role.pk),
                                          initial={"role": role, "start": max(start, role.phase.start_date),
                                                   "end": min(end, role.phase.end_date)}))
    return render(request, "shifts/availability.html", ctx)


@login_required
@require_POST
def availability_toggle(request):
    role = get_object_or_404(Role, pk=request.POST.get("role"))
    try:
        d = dt.date.fromisoformat(request.POST.get("date", ""))
    except ValueError:
        raise Http404
    try:
        S.cycle_availability(request.user, role, d)
    except PermissionError:
        return HttpResponseForbidden("Not eligible for this role.")
    cell = {"date": d, "active": d in set(S.role_working_days(role, d, d)),
            "av": Availability.objects.filter(user=request.user, role=role, date=d).first(),
            "assigned": Assignment.objects.filter(user=request.user, role=role, date=d).exists()}
    return render(request, "shifts/partials/avail_cell.html", {"c": cell, "role": role})


@login_required
@require_POST
def availability_range(request):
    form = AvailabilityRangeForm(request.POST, roles=S.eligible_roles(request.user))
    if not form.is_valid():
        for e in form.errors.values():
            messages.error(request, e.as_text())
        return _back(request, "availability")
    c = form.cleaned_data
    dates = list(S.daterange(c["start"], c["end"]))
    try:
        n = S.set_availability(request.user, c["role"], dates, c["state"], c["comment"])
    except PermissionError:
        return HttpResponseForbidden("Not eligible for this role.")
    label = "cleared" if c["state"] == "clear" else dict(Availability.STATES)[c["state"]].lower()
    messages.success(request, f"{n} working day(s) marked {label} for {c['role'].code}.")
    return _back(request, "availability")


# --------------------------------------------------------------------------- me
@login_required
def me_view(request):
    u = request.user
    t = S.today()
    elig = Eligibility.objects.filter(user=u).select_related("role__phase")
    av_by_role = {}
    for a in Availability.objects.filter(user=u).select_related("role").order_by("role", "date"):
        av_by_role.setdefault(a.role, []).append(a.date)
    av_ranges = [(r, S.compress_dates(ds), len(ds)) for r, ds in av_by_role.items()]
    qs = Assignment.objects.filter(user=u).select_related("role__phase")
    return render(request, "shifts/me.html", {
        "elig": elig, "av_ranges": av_ranges,
        "upcoming": qs.filter(date__gte=t), "past": qs.filter(date__lt=t).order_by("-date")[:200],
    })


@login_required
def me_csv(request):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="my-iwcd-shifts.csv"'
    w = csv.writer(resp)
    w.writerow(["date", "role", "phase", "flag", "source", "start_jst", "end_jst"])
    for a in Assignment.objects.filter(user=request.user).select_related("role__phase"):
        w.writerow([a.date, a.role.code, a.role.phase.name, a.flag, a.source, settings.SHIFT_START, settings.SHIFT_END])
    return resp


@login_required
@require_POST
def withdraw(request, pk):
    a = get_object_or_404(Assignment, pk=pk, user=request.user)
    if a.source == Assignment.SOURCE_IMPORTED:
        messages.error(request, "Shifter slots come from the Hyper-K central scheduler; change them there.")
    elif a.date < S.today():
        messages.error(request, "Past shifts cannot be withdrawn.")
    else:
        S.unassign([a], actor=request.user, verb="withdraw")
        messages.success(request, f"Withdrawn from {a.role.code} on {a.date:%d %b %Y}. The coordinator has been notified.")
    return redirect("me")


# --------------------------------------------------------------------------- coordinator
def _assign_users(role):
    return User.objects.filter(
        Q(eligibilities__role=role, eligibilities__eligible=True) | Q(is_staff=True), is_active=True
    ).distinct().order_by("last_name", "first_name")


@coordinator_required
def coverage_view(request):
    roles = list(Role.objects.filter(self_service=True).select_related("phase"))
    if not roles:
        messages.warning(request, "No roles yet. Run 'python manage.py seed_iwcd' or add roles in the admin.")
        return redirect("calendar")
    role = next((r for r in roles if str(r.id) == request.GET.get("role")), roles[0])
    default = min(max(role.phase.start_date, S.today()), role.phase.end_date).replace(day=1)
    first, start, end, ctx = _month_ctx(request, default)
    cover = S.coverage([role], start, end)
    rows = [cover[k] for k in sorted(cover, key=lambda k: k[1])]
    users = _assign_users(role)
    summary = {s: sum(1 for c in rows if c.status == s) for s in ("filled", "avail", "gap")}
    ctx.update(
        roles=roles, role=role, rows=rows, summary=summary, users=users,
        assign_form=AssignRangeForm(users=users, initial={"role": role, "start": rows[0].date if rows else None,
                                                          "end": rows[-1].date if rows else None}),
        unassign_form=UnassignRangeForm(initial={"role": role}),
        eligible_count=S.eligible_users(role).count(),
    )
    return render(request, "shifts/coord/coverage.html", ctx)


@coordinator_required
@require_POST
def assign_range(request):
    role = get_object_or_404(Role, pk=request.POST.get("role"))
    form = AssignRangeForm(request.POST, users=_assign_users(role))
    back = f"{reverse('coverage')}?role={role.id}&m={request.POST.get('start', '')[:7]}"
    if not form.is_valid():
        for e in form.errors.values():
            messages.error(request, e.as_text())
        return redirect(back)
    c = form.cleaned_data
    plan = S.plan_assignment(c["role"], c["user"], c["start"], c["end"], c["flag"],
                             c["first_two_flag"], c["only_available"])
    if request.POST.get("confirm") == "1" and plan.days:
        created = S.apply_plan(plan, request.user, c["note"])
        messages.success(request, f"Assigned {c['user'].name} as {role.code} on {len(created)} day(s); email sent.")
        return redirect(back)
    return render(request, "shifts/coord/assign_preview.html", {"plan": plan, "form": form, "back": back})


@coordinator_required
@require_POST
def assign_day(request):
    role = get_object_or_404(Role, pk=request.POST.get("role"))
    user = get_object_or_404(User, pk=request.POST.get("user"))
    d = dt.date.fromisoformat(request.POST["date"])
    flag = request.POST.get("flag") or Assignment.FLAG_NONE
    if flag not in dict(Assignment.FLAGS):
        flag = Assignment.FLAG_NONE
    plan = S.plan_assignment(role, user, d, d, flag)
    created = S.apply_plan(plan, request.user)
    if created:
        messages.success(request, f"Assigned {user.name} as {role.code} on {d:%a %d %b}.")
    for w in plan.warnings:
        if not w.startswith("Block"):  # single-day assigns are usually part of a block being built
            messages.warning(request, w)
    return _back(request, "coverage")


@coordinator_required
@require_POST
def unassign_one(request, pk):
    a = get_object_or_404(Assignment, pk=pk)
    S.unassign([a], actor=request.user)
    messages.success(request, f"Removed {a.user.name} from {a.role.code} on {a.date:%d %b}.")
    return _back(request, "coverage")


@coordinator_required
@require_POST
def unassign_range(request):
    form = UnassignRangeForm(request.POST)
    if form.is_valid():
        c = form.cleaned_data
        qs = Assignment.objects.filter(role=c["role"], user=c["user"], date__range=(c["start"], c["end"]))
        n = S.unassign(qs.select_related("user", "role"), actor=request.user)
        messages.success(request, f"Removed {n} assignment(s).")
    else:
        messages.error(request, "Invalid unassign request.")
    return _back(request, "coverage")


@coordinator_required
def eligibility_view(request):
    preview = None
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "add":
            f = EligibilityAddForm(request.POST)
            if f.is_valid():
                c = f.cleaned_data
                user, _ = importers._get_or_create_user(c["email"].lower(), c["name"])
                Eligibility.objects.update_or_create(user=user, role=c["role"], defaults={
                    "eligible": c["eligible"], "note": c["note"], "confirmed_on": c["confirmed_on"]})
                audit(request.user, "eligibility_set", subject_user=user, role=c["role"],
                      note=f"{'eligible' if c['eligible'] else 'not eligible'} {c['note']}".strip())
                messages.success(request, f"Saved {user.email} for {c['role'].code}.")
                return redirect("eligibility")
            messages.error(request, "Please correct the form.")
        elif action == "upload":
            f = CsvUploadForm(request.POST, request.FILES)
            if f.is_valid():
                name, text = f.cleaned_data["file"]
                rows, errors = importers.parse_eligibility(text)
                request.session["elig_csv"] = [name, text]
                preview = {"name": name, "rows": rows, "errors": errors}
            else:
                messages.error(request, "; ".join(e for errs in f.errors.values() for e in errs))
        elif action == "commit":
            name, text = request.session.pop("elig_csv", [None, None])
            if text is None:
                messages.error(request, "Nothing to commit; upload again.")
            else:
                rows, errors = importers.parse_eligibility(text)
                n = importers.commit_eligibility(rows, request.user, name)
                messages.success(request, f"Loaded {n} eligibility row(s)" + (f"; {len(errors)} line(s) skipped." if errors else "."))
            return redirect("eligibility")
    elig = Eligibility.objects.select_related("user", "role__phase").order_by("role__phase__start_date", "role__order", "user__last_name")
    return render(request, "shifts/coord/eligibility.html", {
        "elig": elig, "add_form": EligibilityAddForm(initial={"eligible": True}),
        "upload_form": CsvUploadForm(), "preview": preview,
    })


@coordinator_required
def import_shifters_view(request):
    preview = None
    if request.method == "POST":
        if request.POST.get("action") == "commit":
            name, text = request.session.pop("shifter_csv", [None, None])
            if text is None:
                messages.error(request, "Nothing to commit; upload again.")
            else:
                rows, errors, warnings = importers.parse_shifters(text)
                n = importers.commit_shifters(rows, request.user, name)
                messages.success(request, f"Imported {n} shifter assignment(s).")
            return redirect("import_shifters")
        f = CsvUploadForm(request.POST, request.FILES)
        if f.is_valid():
            name, text = f.cleaned_data["file"]
            rows, errors, warnings = importers.parse_shifters(text)
            request.session["shifter_csv"] = [name, text]
            preview = {"name": name, "rows": rows, "errors": errors, "warnings": warnings,
                       "start": min((r["date"] for r in rows), default=None),
                       "end": max((r["date"] for r in rows), default=None)}
        else:
            messages.error(request, "; ".join(e for errs in f.errors.values() for e in errs))
    from .models import ShiftImport
    return render(request, "shifts/coord/import_shifters.html", {
        "form": CsvUploadForm(), "preview": preview,
        "history": ShiftImport.objects.filter(kind="shifters").select_related("admin")[:20],
    })


@coordinator_required
def totals_view(request):
    try:
        year = int(request.GET.get("year", S.today().year))
    except ValueError:
        year = S.today().year
    rows = S.yearly_totals(year)
    if request.GET.get("format") == "csv":
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="iwcd-totals-{year}.csv"'
        w = csv.writer(resp)
        w.writerow(["name", "email", "institution", "role", "counted_shifts", "hours",
                    "overlap_days", "onboarding_days", "of_which_cover"])
        for r in rows:
            w.writerow([r["user"].name, r["user"].email, r["user"].institution, r["role"], r["shifts"],
                        r["hours"], r["overlap"], r["onboarding"], r["cover"]])
        return resp
    return render(request, "shifts/coord/totals.html", {"rows": rows, "year": year})


@coordinator_required
def export_assignments(request):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="iwcd-assignments.csv"'
    w = csv.writer(resp)
    w.writerow(["date", "phase", "role", "name", "email", "institution", "flag", "source", "note"])
    for a in Assignment.objects.select_related("role__phase", "user").order_by("date", "role__order"):
        w.writerow([a.date, a.role.phase.name, a.role.code, a.user.name, a.user.email, a.user.institution,
                    a.flag, a.source, a.note])
    return resp


@coordinator_required
def export_availability(request):
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="iwcd-availability.csv"'
    w = csv.writer(resp)
    w.writerow(["date", "role", "name", "email", "state", "comment"])
    for a in Availability.objects.select_related("role", "user").order_by("date", "role__order"):
        w.writerow([a.date, a.role.code, a.user.name, a.user.email, a.state, a.comment])
    return resp
