"""Fake people + availability for trying the tool locally. NEVER run on the production server."""
import datetime as dt

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from shifts import services as S
from shifts.models import Eligibility, Role, User

PEOPLE = [
    ("ana.demo@example.org", "Ana", "Demo", ["SL1", "SLB"]),
    ("ben.demo@example.org", "Ben", "Demo", ["SL1"]),
    ("chloe.demo@example.org", "Chloe", "Demo", ["SLA", "SLB"]),
    ("dev.demo@example.org", "Dev", "Demo", ["SLA"]),
]


class Command(BaseCommand):
    help = "Create demo users, eligibility and availability (local testing only)."

    def handle(self, *args, **o):
        if not settings.DEBUG:
            raise CommandError("demo_data only runs with DEBUG=True (local machine).")
        if not Role.objects.exists():
            raise CommandError("Run 'python manage.py seed_iwcd' first.")
        roles = {r.code: r for r in Role.objects.filter(self_service=True)}
        for i, (email, first, last, codes) in enumerate(PEOPLE):
            user, _ = User.objects.get_or_create(email=email, defaults={"first_name": first, "last_name": last})
            for code in codes:
                role = roles[code]
                Eligibility.objects.update_or_create(user=user, role=role, defaults={"eligible": True})
                start = role.phase.start_date + dt.timedelta(days=7 * i)
                S.set_availability(user, role, list(S.daterange(start, start + dt.timedelta(days=13))),
                                   "preferred" if i % 2 == 0 else "available", "demo")
                S.set_availability(user, role, list(S.daterange(start + dt.timedelta(days=21),
                                                                start + dt.timedelta(days=34))), "if_needed")
        self.stdout.write(self.style.SUCCESS(f"Demo data created for {len(PEOPLE)} people."))
