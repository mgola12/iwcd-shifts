"""Send T-7 and T-1 reminders for assignments. Run once a day (systemd timer)."""
import datetime as dt

from django.core.management.base import BaseCommand

from shifts import notify
from shifts.models import Assignment
from shifts.services import today


class Command(BaseCommand):
    help = "Email reminders 7 days and 1 day before each assigned shift."

    def add_arguments(self, parser):
        parser.add_argument("--include-shifters", action="store_true",
                            help="Also remind imported shifters (normally the central scheduler does this).")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        t = today()
        sent = 0
        for days, field in ((7, "reminded_t7"), (1, "reminded_t1")):
            qs = Assignment.objects.filter(date=t + dt.timedelta(days=days), **{field: False}) \
                .select_related("user", "role__phase")
            if not o["include_shifters"]:
                qs = qs.exclude(source=Assignment.SOURCE_IMPORTED)
            for a in qs:
                if o["dry_run"]:
                    self.stdout.write(f"would remind {a.user.email} {a.role.code} {a.date} (T-{days})")
                    continue
                if notify.reminder(a, days):
                    setattr(a, field, True)
                    a.save(update_fields=[field])
                    sent += 1
        self.stdout.write(f"{sent} reminder(s) sent for {t}.")
