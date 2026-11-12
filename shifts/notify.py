"""Plain-text emails. Failures are logged, never raised to the user."""
import logging

from django.conf import settings
from django.core.mail import send_mail

log = logging.getLogger(__name__)


def _send(subject, body, to):
    to = [t for t in to if t]
    if not to:
        return False
    try:
        send_mail(f"[IWCD Shifts] {subject}", body + _footer(), settings.DEFAULT_FROM_EMAIL, to)
        return True
    except Exception:  # noqa: BLE001
        log.exception("Email to %s failed: %s", to, subject)
        return False


def _footer():
    return (f"\n\n--\nIWCD shift tool: {settings.BASE_URL}/me/\n"
            f"All times JST. Shifts run {settings.SHIFT_START}-{settings.SHIFT_END}, J-PARC RD Building.")


def coordinator_emails():
    if settings.COORDINATOR_EMAILS:
        return settings.COORDINATOR_EMAILS
    from .models import User
    return list(User.objects.filter(is_staff=True, is_active=True).values_list("email", flat=True))


def _date_lines(assignments):
    return "\n".join(
        f"  {a.date:%a %d %b %Y}" + (f"  ({a.get_flag_display()})" if a.flag != "none" else "")
        for a in assignments
    )


def assignment_notice(user, role, assignments):
    body = (f"Dear {user.get_short_name()},\n\nYou have been assigned as {role.name} "
            f"({role.phase.name}) on the following day(s):\n\n{_date_lines(assignments)}\n\n"
            "You will get reminders 7 days and 1 day before each shift. If you can no longer "
            "do a shift, withdraw on the 'My shifts' page; the coordinator will be notified.")
    if role.phase.manual_url:
        body += f"\n\nPhase manual: {role.phase.manual_url}"
    return _send(f"Assigned: {role.code} {assignments[0].date:%d %b}"
                 + (f" - {assignments[-1].date:%d %b %Y}" if len(assignments) > 1 else ""),
                 body, [user.email])


def unassign_notice(user, role, dates):
    lines = "\n".join(f"  {d:%a %d %b %Y}" for d in dates)
    return _send(f"Removed: {role.code} assignment",
                 f"Dear {user.get_short_name()},\n\nThe coordinator removed you as {role.name} on:\n\n"
                 f"{lines}\n\nPlease contact the coordinator if this is unexpected.", [user.email])


def withdraw_alert(user, role, dates):
    lines = "\n".join(f"  {d:%a %d %b %Y}" for d in dates)
    return _send(f"Withdrawal: {user.name} ({role.code})",
                 f"{user.name} <{user.email}> withdrew from {role.name} on:\n\n{lines}\n\n"
                 f"Coverage: {settings.BASE_URL}/coord/coverage/?role={role.id}&m={dates[0]:%Y-%m}",
                 coordinator_emails())


def reminder(assignment, days_before):
    a = assignment
    when = "tomorrow" if days_before == 1 else f"in {days_before} days"
    body = (f"Dear {a.user.get_short_name()},\n\nReminder: you are {a.role.name} {when}, "
            f"{a.date:%A %d %B %Y}, {settings.SHIFT_START}-{settings.SHIFT_END} JST, J-PARC RD Building.")
    if a.flag != "none":
        body += f"\nNote: {a.get_flag_display()}."
    if a.role.phase.manual_url:
        body += f"\n\nPhase manual: {a.role.phase.manual_url}"
    return _send(f"Reminder: {a.role.code} on {a.date:%a %d %b}", body, [a.user.email])


def magic_link(user, url):
    return _send("Your sign-in link",
                 f"Hello {user.get_short_name()},\n\nUse this link to sign in (valid 15 minutes, once):\n\n"
                 f"{url}\n\nIf you did not ask for this, ignore this email.", [user.email])
