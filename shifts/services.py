"""Business logic: working days, coverage, availability, assignment planning."""
import calendar as pycal
import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from . import notify
from .models import Assignment, Availability, ClosedDay, Eligibility, Phase, Role, audit


# --------------------------------------------------------------------------- dates
def today():
    return timezone.localdate()  # TIME_ZONE is Asia/Tokyo


def month_bounds(year, month):
    last = pycal.monthrange(year, month)[1]
    return dt.date(year, month, 1), dt.date(year, month, last)


def parse_month(value, default=None):
    try:
        y, m = (int(x) for x in value.split("-")[:2])
        return dt.date(y, m, 1)
    except (AttributeError, ValueError):
        return default


def shift_month(first, delta):
    m = first.month - 1 + delta
    return dt.date(first.year + m // 12, m % 12 + 1, 1)


def closed_days(start, end):
    return dict(ClosedDay.objects.filter(date__range=(start, end)).values_list("date", "reason"))


def daterange(start, end):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


def working_days(start, end, closed=None):
    """Mon-Fri days in [start, end] that are not ClosedDay."""
    if start > end:
        return []
    if closed is None:
        closed = closed_days(start, end)
    return [d for d in daterange(start, end) if d.weekday() < 5 and d not in closed]


def role_working_days(role, start=None, end=None, closed=None):
    s = max(start or role.phase.start_date, role.phase.start_date)
    e = min(end or role.phase.end_date, role.phase.end_date)
    return working_days(s, e, closed)


def month_weeks(first):
    """List of weeks, each a list of 5 dates (Mon-Fri) or None outside the month."""
    _, last = month_bounds(first.year, first.month)
    start = first - dt.timedelta(days=first.weekday())
    weeks = []
    while start <= last:
        week = []
        for i in range(5):
            d = start + dt.timedelta(days=i)
            week.append(d if d.month == first.month else None)
        if any(week):
            weeks.append(week)
        start += dt.timedelta(days=7)
    return weeks


def compress_dates(dates):
    """[d1, d2, ...] -> [(start, end), ...] merging consecutive calendar days and weekends."""
    out = []
    for d in sorted(dates):
        if out:
            s, e = out[-1]
            gap = (d - e).days
            if gap == 1 or (gap <= 3 and all(x.weekday() >= 5 for x in daterange(e + dt.timedelta(1), d - dt.timedelta(1)))):
                out[-1] = (s, d)
                continue
        out.append((d, d))
    return out


# --------------------------------------------------------------------------- eligibility
def eligible_roles(user):
    return Role.objects.filter(
        eligibilities__user=user, eligibilities__eligible=True, self_service=True
    ).select_related("phase").order_by("phase__start_date", "order")


def is_eligible(user, role):
    return Eligibility.objects.filter(user=user, role=role, eligible=True).exists()


def eligible_users(role):
    from .models import User
    return User.objects.filter(eligibilities__role=role, eligibilities__eligible=True, is_active=True)


# --------------------------------------------------------------------------- availability
def set_availability(user, role, dates, state, comment="", actor=None):
    """state in Availability.STATE_ORDER or 'clear'. Returns number of days changed."""
    if not role.self_service or not is_eligible(user, role):
        raise PermissionError("Not eligible for this role")
    valid = set(role_working_days(role, min(dates), max(dates))) if dates else set()
    dates = [d for d in dates if d in valid]
    if not dates:
        return 0
    with transaction.atomic():
        if state == "clear":
            n, _ = Availability.objects.filter(user=user, role=role, date__in=dates).delete()
            verb = "availability_removed"
        else:
            n = 0
            for d in dates:
                obj, created = Availability.objects.get_or_create(
                    user=user, role=role, date=d, defaults={"state": state, "comment": comment}
                )
                if not created:
                    obj.state = state
                    if comment:
                        obj.comment = comment
                    obj.save()
                n += 1
            verb = "availability_set"
        if n:
            audit(actor or user, verb, subject_user=user, role=role, date=min(dates),
                  note=f"{min(dates)}..{max(dates)} ({len(dates)} d) {state} {comment}".strip())
    return n


def cycle_availability(user, role, day):
    """Click cycle: none -> preferred -> available -> if_needed -> none."""
    obj = Availability.objects.filter(user=user, role=role, date=day).first()
    order = Availability.STATE_ORDER
    if obj is None:
        nxt = order[0]
    else:
        i = order.index(obj.state)
        nxt = order[i + 1] if i + 1 < len(order) else "clear"
    set_availability(user, role, [day], nxt)
    return None if nxt == "clear" else nxt


# --------------------------------------------------------------------------- coverage
@dataclass
class DayCover:
    date: dt.date
    role: Role
    assignments: list = field(default_factory=list)
    available: list = field(default_factory=list)

    @property
    def filled(self):
        return sum(1 for a in self.assignments if a.fills_slot)

    @property
    def status(self):
        if self.filled >= self.role.slots_per_day:
            return "filled"
        if self.available:
            return "avail"
        return "gap"


def coverage(roles, start, end):
    """{(role_id, date): DayCover} for every working day of each role in [start, end]."""
    roles = list(roles)
    closed = closed_days(start, end)
    out = {}
    for r in roles:
        for d in role_working_days(r, start, end, closed):
            out[(r.id, d)] = DayCover(d, r)
    if not out:
        return out
    for a in Assignment.objects.filter(role__in=roles, date__range=(start, end)).select_related("user", "role"):
        if (a.role_id, a.date) in out:
            out[(a.role_id, a.date)].assignments.append(a)
    elig = set(Eligibility.objects.filter(role__in=roles, eligible=True).values_list("user_id", "role_id"))
    for av in Availability.objects.filter(role__in=roles, date__range=(start, end)).select_related("user"):
        if (av.user_id, av.role_id) in elig and (av.role_id, av.date) in out:
            out[(av.role_id, av.date)].available.append(av)
    rank = {s: i for i, s in enumerate(Availability.STATE_ORDER)}
    for c in out.values():
        c.available.sort(key=lambda a: (rank[a.state], a.user.name))
    return out


def phases_in(start, end):
    return Phase.objects.filter(start_date__lte=end, end_date__gte=start, subsystem__active=True)


def roles_in(start, end, self_service=None):
    qs = Role.objects.filter(phase__in=phases_in(start, end)).select_related("phase")
    if self_service is not None:
        qs = qs.filter(self_service=self_service)
    return qs.order_by("phase__start_date", "order")


# --------------------------------------------------------------------------- assignment
@dataclass
class Plan:
    role: Role
    user: object
    days: list  # [(date, flag)]
    warnings: list
    skipped: list  # dates already assigned to this person


def _runs(days_sorted, all_working):
    """Split assigned dates into runs of consecutive *working* days."""
    idx = {d: i for i, d in enumerate(all_working)}
    runs, cur = [], []
    for d in days_sorted:
        if cur and idx.get(d, -99) == idx.get(cur[-1], -99) + 1:
            cur.append(d)
        else:
            if cur:
                runs.append(cur)
            cur = [d]
    if cur:
        runs.append(cur)
    return runs


def plan_assignment(role, user, start, end, flag=Assignment.FLAG_NONE, first_two_flag="",
                    only_available=False):
    warnings = []
    days = role_working_days(role, start, end)
    avail = dict(Availability.objects.filter(user=user, role=role, date__in=days).values_list("date", "state"))
    if only_available:
        days = [d for d in days if d in avail]
    existing = set(Assignment.objects.filter(role=role, user=user, date__in=days).values_list("date", flat=True))
    skipped = sorted(existing)
    days = [d for d in days if d not in existing]

    if not days:
        return Plan(role, user, [], ["No working days to assign in that range."], skipped)

    if not is_eligible(user, role) and not user.is_staff:
        warnings.append(f"{user.name} is not on the eligible list for {role.code}.")

    missing = [d for d in days if d not in avail]
    if missing and not user.is_staff:
        warnings.append(f"{user.name} did not mark availability on {len(missing)} day(s): "
                        + ", ".join(f"{d:%d %b}" for d in missing[:8]) + (" ..." if len(missing) > 8 else ""))

    flags = {d: flag for d in days}
    if first_two_flag:
        for d in days[:2]:
            flags[d] = first_two_flag

    # Slots already full (only matters for slot-filling flags)
    counts = defaultdict(int)
    for a in Assignment.objects.filter(role=role, date__in=days).exclude(user=user):
        if a.fills_slot:
            counts[a.date] += 1
    full = [d for d in days if counts[d] >= role.slots_per_day and flags[d] not in Assignment.NON_FILLING]
    if full:
        warnings.append(f"Slot already filled on {len(full)} day(s): "
                        + ", ".join(f"{d:%d %b}" for d in full[:8]))

    # Same person on another role the same day
    clash = Assignment.objects.filter(user=user, date__in=days).exclude(role=role).values_list("date", flat=True)
    if clash:
        warnings.append(f"{user.name} is already assigned to another role on: "
                        + ", ".join(f"{d:%d %b}" for d in sorted(set(clash))[:8]))

    # Block length (consecutive working days for this person + role, including existing)
    all_wd = role_working_days(role)
    mine = sorted(set(days) | set(Assignment.objects.filter(role=role, user=user).values_list("date", flat=True)))
    short = [r for r in _runs(mine, all_wd) if len(r) < settings.MIN_BLOCK_DAYS and set(r) & set(days)]
    for r in short:
        warnings.append(f"Block {r[0]:%d %b}-{r[-1]:%d %b} is {len(r)} working day(s); "
                        f"minimum is {settings.MIN_BLOCK_DAYS}.")

    # SLA hand-over overlap
    if role.code == "SLA" and not user.is_staff:
        before = Assignment.objects.filter(role=role, date__lt=days[0]).exclude(user=user).exists()
        if before:
            others_first2 = Assignment.objects.filter(role=role, date__in=days[:2]).exclude(user=user).count()
            if others_first2 < 2:
                warnings.append("No 2-day overlap with the outgoing Shift Leader A on the first two days "
                                "(assign the outgoing SLA on those days, or check the hand-over).")
            if first_two_flag != Assignment.FLAG_OVERLAP:
                warnings.append("Incoming SLA: consider marking the first two days as 'overlap'.")

    return Plan(role, user, [(d, flags[d]) for d in days], warnings, skipped)


def apply_plan(plan, actor, note="", notify_user=True):
    created = []
    with transaction.atomic():
        for d, flag in plan.days:
            a, was_created = Assignment.objects.get_or_create(
                role=plan.role, date=d, user=plan.user,
                defaults={"flag": flag, "source": Assignment.SOURCE_ADMIN, "created_by": actor, "note": note},
            )
            if was_created:
                created.append(a)
        if created:
            audit(actor, "assign", subject_user=plan.user, role=plan.role, date=created[0].date,
                  note=f"{created[0].date}..{created[-1].date} ({len(created)} d)")
    if created and notify_user:
        notify.assignment_notice(plan.user, plan.role, created)
    return created


def unassign(assignments, actor, verb="unassign", notify_user=True):
    assignments = list(assignments)
    if not assignments:
        return 0
    user, role = assignments[0].user, assignments[0].role
    dates = sorted(a.date for a in assignments)
    with transaction.atomic():
        for a in assignments:
            audit(actor, verb, subject_user=a.user, role=a.role, date=a.date, note=a.get_flag_display())
            a.delete()
    if verb == "withdraw":
        notify.withdraw_alert(user, role, dates)
    elif notify_user and user != actor:
        notify.unassign_notice(user, role, dates)
    return len(dates)


# --------------------------------------------------------------------------- totals
def yearly_totals(year):
    """Per user and role: counted shifts, overlap days, onboarding days, hours."""
    rows = defaultdict(lambda: {"shifts": 0, "overlap": 0, "onboarding": 0, "cover": 0})
    qs = Assignment.objects.filter(date__year=year).select_related("user", "role")
    for a in qs:
        r = rows[(a.user, a.role.code)]
        if a.flag == Assignment.FLAG_OVERLAP:
            r["overlap"] += 1
        elif a.flag == Assignment.FLAG_ONBOARDING:
            r["onboarding"] += 1
        else:
            r["shifts"] += 1
            if a.flag == Assignment.FLAG_COVER:
                r["cover"] += 1
    out = []
    for (user, code), r in rows.items():
        r.update(user=user, role=code, hours=r["shifts"] * settings.SHIFT_HOURS)
        out.append(r)
    out.sort(key=lambda r: (r["user"].name.lower(), r["role"]))
    return out
