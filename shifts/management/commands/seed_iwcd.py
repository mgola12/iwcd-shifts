"""Create the SM-assembly phases, roles and Japanese public holidays. Safe to re-run."""
import datetime as dt

from django.core.management.base import BaseCommand

from shifts.models import ClosedDay, Phase, Role, Subsystem

D = dt.date.fromisoformat

# Japanese national holidays falling on weekdays, 2027 - mid 2028.
# Verify against the official Cabinet Office list and the J-PARC calendar, and add
# J-PARC closures (e.g. year-end shutdown) as ClosedDay rows in the admin.
HOLIDAYS = {
    "2027-01-01": "New Year's Day", "2027-01-11": "Coming of Age Day",
    "2027-02-11": "National Foundation Day", "2027-02-23": "Emperor's Birthday",
    "2027-03-22": "Vernal Equinox Day (substitute)", "2027-04-29": "Showa Day",
    "2027-05-03": "Constitution Memorial Day", "2027-05-04": "Greenery Day", "2027-05-05": "Children's Day",
    "2027-07-19": "Marine Day", "2027-08-11": "Mountain Day", "2027-09-20": "Respect for the Aged Day",
    "2027-09-23": "Autumnal Equinox Day", "2027-10-11": "Sports Day", "2027-11-03": "Culture Day",
    "2027-11-23": "Labour Thanksgiving Day",
    "2028-01-10": "Coming of Age Day", "2028-02-11": "National Foundation Day",
    "2028-02-23": "Emperor's Birthday", "2028-03-20": "Vernal Equinox Day",
    "2028-05-03": "Constitution Memorial Day", "2028-05-04": "Greenery Day", "2028-05-05": "Children's Day",
    "2028-07-17": "Marine Day",
}

PHASES = [
    {
        "code": "P1", "name": "Phase 1: SM pre-assembly", "start": "2027-06-01", "end": "2027-12-31",
        "color": "#0d6efd", "order": 1,
        "roles": [
            ("SL1", "Shift Leader (Phase 1)", 1, True, "#0d6efd",
             "mPMT testing (day before), SM frame assembly, mounting mPMTs, turning the SM upright, "
             "installing it in the vertical storage carts."),
            ("SHIFTER", "Shifter", 2, False, "#6c757d", "Imported from the Hyper-K central shift scheduler."),
        ],
    },
    {
        "code": "P2", "name": "Phase 2: preparation for installation", "start": "2028-01-01", "end": "2028-07-31",
        "color": "#198754", "order": 2,
        "roles": [
            ("SLA", "Shift Leader A", 1, True, "#fd7e14",
             "OD PMT assemblies and cables: OD PMT QA, WLS plate QA, OD PMT + WLS + holder + bracket + small "
             "Tyvek assembly, OD cable pre-cut and capping, cable bundles, labelling, database updates."),
            ("SLB", "Shift Leader B", 1, True, "#6f42c1",
             "Final SM assembly: SM to vertical stand, mPMT cables install and test, OD PMT assemblies and "
             "large Tyvek, cable spooling, labelling, database updates, final QC, SM back to transport frame."),
            ("SHIFTER", "Shifter", 2, False, "#6c757d", "Imported from the Hyper-K central shift scheduler."),
        ],
    },
]


class Command(BaseCommand):
    help = "Seed subsystem, Phase 1/2, roles (SL1, SLA, SLB, SHIFTER) and Japanese holidays."

    def handle(self, *args, **opts):
        sub, _ = Subsystem.objects.get_or_create(code="SM", defaults={"name": "IWCD Super-Module assembly"})
        for p in PHASES:
            phase, created = Phase.objects.get_or_create(
                subsystem=sub, code=p["code"],
                defaults={"name": p["name"], "start_date": D(p["start"]), "end_date": D(p["end"]),
                          "color": p["color"], "order": p["order"]},
            )
            self.stdout.write(f"{'Created' if created else 'Exists '} {phase} {phase.start_date}..{phase.end_date}")
            for i, (code, name, slots, self_service, color, desc) in enumerate(p["roles"]):
                Role.objects.get_or_create(phase=phase, code=code, defaults={
                    "name": name, "slots_per_day": slots, "self_service": self_service,
                    "color": color, "order": i, "description": desc})
        n = 0
        for d, reason in HOLIDAYS.items():
            _, c = ClosedDay.objects.get_or_create(date=D(d), defaults={"reason": reason})
            n += c
        self.stdout.write(self.style.SUCCESS(f"Done. {n} holiday(s) added. Check dates in the admin."))
