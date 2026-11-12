import datetime as dt
import re

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from . import importers, services as S
from .models import Assignment, Availability, Eligibility, Role, User

D = dt.date.fromisoformat


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   COORDINATOR_EMAILS=["coord@example.org"], BASE_URL="http://testserver")
class IwcdTests(TestCase):
    def setUp(self):
        call_command("seed_iwcd", stdout=open("/dev/null", "w"))
        self.sl1 = Role.objects.get(code="SL1")
        self.sla = Role.objects.get(code="SLA")
        self.coord = User.objects.create_user("coord@example.org", first_name="Co", last_name="Ord", is_staff=True)
        self.alice = User.objects.create_user("alice@example.org", first_name="Alice", last_name="A")
        self.bob = User.objects.create_user("bob@example.org", first_name="Bob", last_name="B")
        Eligibility.objects.create(user=self.alice, role=self.sl1)
        Eligibility.objects.create(user=self.alice, role=self.sla)
        Eligibility.objects.create(user=self.bob, role=self.sla)

    # ---- dates
    def test_working_days_skip_weekends_and_holidays(self):
        days = S.working_days(D("2027-07-12"), D("2027-07-23"))
        self.assertNotIn(D("2027-07-17"), days)  # Saturday
        self.assertNotIn(D("2027-07-19"), days)  # Marine Day
        self.assertEqual(len(days), 9)

    def test_compress_dates_bridges_weekend(self):
        r = S.compress_dates([D("2027-06-03"), D("2027-06-04"), D("2027-06-07")])
        self.assertEqual(r, [(D("2027-06-03"), D("2027-06-07"))])

    # ---- availability
    def test_availability_requires_eligibility(self):
        with self.assertRaises(PermissionError):
            S.set_availability(self.bob, self.sl1, [D("2027-06-01")], "available")

    def test_availability_range_only_working_days_in_phase(self):
        n = S.set_availability(self.alice, self.sl1, list(S.daterange(D("2027-05-28"), D("2027-06-08"))), "preferred")
        self.assertEqual(n, 6)  # Jun 1-4, 7-8
        self.assertEqual(Availability.objects.filter(user=self.alice).count(), 6)
        S.set_availability(self.alice, self.sl1, [D("2027-06-01")], "clear")
        self.assertEqual(Availability.objects.filter(user=self.alice).count(), 5)

    def test_toggle_cycles(self):
        self.client.force_login(self.alice)
        url = reverse("availability_toggle")
        states = []
        for _ in range(4):
            self.client.post(url, {"role": self.sl1.id, "date": "2027-06-02"})
            a = Availability.objects.filter(user=self.alice, role=self.sl1, date=D("2027-06-02")).first()
            states.append(a.state if a else None)
        self.assertEqual(states, ["preferred", "available", "if_needed", None])

    # ---- assignment
    def test_plan_short_block_warns_and_apply_emails(self):
        S.set_availability(self.alice, self.sl1, [D("2027-06-01"), D("2027-06-02")], "available")
        plan = S.plan_assignment(self.sl1, self.alice, D("2027-06-01"), D("2027-06-03"))
        self.assertEqual(len(plan.days), 3)
        self.assertTrue(any("minimum is 5" in w for w in plan.warnings))
        self.assertTrue(any("did not mark availability" in w for w in plan.warnings))
        created = S.apply_plan(plan, self.coord)
        self.assertEqual(len(created), 3)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("alice@example.org", mail.outbox[0].to)

    def test_full_block_no_block_warning(self):
        plan = S.plan_assignment(self.sl1, self.alice, D("2027-06-07"), D("2027-06-11"))
        self.assertFalse(any("minimum" in w for w in plan.warnings))

    def test_sla_overlap(self):
        S.apply_plan(S.plan_assignment(self.sla, self.bob, D("2028-01-04"), D("2028-01-14")), self.coord)
        plan = S.plan_assignment(self.sla, self.alice, D("2028-01-17"), D("2028-01-21"))
        self.assertTrue(any("overlap" in w for w in plan.warnings))
        plan = S.plan_assignment(self.sla, self.alice, D("2028-01-13"), D("2028-01-21"), first_two_flag="overlap")
        self.assertFalse(any("No 2-day overlap" in w for w in plan.warnings))
        S.apply_plan(plan, self.coord)
        cov = S.coverage([self.sla], D("2028-01-13"), D("2028-01-13"))[(self.sla.id, D("2028-01-13"))]
        self.assertEqual(cov.filled, 1)  # overlap person does not fill the slot
        self.assertEqual(cov.status, "filled")

    def test_withdraw_notifies_coordinator(self):
        S.apply_plan(S.plan_assignment(self.sl1, self.alice, D("2027-06-07"), D("2027-06-11")), self.coord,
                     notify_user=False)
        a = Assignment.objects.filter(user=self.alice).first()
        self.client.force_login(self.alice)
        self.client.post(reverse("withdraw", args=[a.pk]))
        self.assertFalse(Assignment.objects.filter(pk=a.pk).exists())
        self.assertIn("coord@example.org", mail.outbox[-1].to)

    def test_totals_separate_overlap(self):
        Assignment.objects.create(role=self.sla, date=D("2028-01-04"), user=self.alice, flag="overlap")
        Assignment.objects.create(role=self.sla, date=D("2028-01-05"), user=self.alice)
        r = S.yearly_totals(2028)[0]
        self.assertEqual((r["shifts"], r["overlap"], r["hours"]), (1, 1, 8))

    # ---- importers
    def test_shifter_import_replaces_range(self):
        text = ("date,name,email,note\n2027-06-01,Carla Diaz,carla@example.org,\n"
                "2027-06-01,Dan E,dan@example.org,\n2027-06-01,Extra P,extra@example.org,\n"
                "2027-06-02,Carla Diaz,carla@example.org,\nbad,x,y,\n")
        rows, errors, warnings = importers.parse_shifters(text)
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(errors), 1)
        self.assertTrue(any("more than 2" in w for w in warnings))
        importers.commit_shifters(rows, self.coord, "a.csv")
        self.assertEqual(Assignment.objects.filter(role__code="SHIFTER").count(), 3)
        rows, _, _ = importers.parse_shifters("date,name,email,note\n2027-06-01,Dan E,dan@example.org,\n")
        importers.commit_shifters(rows, self.coord, "b.csv")
        self.assertEqual(Assignment.objects.filter(role__code="SHIFTER").count(), 2)  # 06-02 outside new range kept

    def test_eligibility_import(self):
        text = "email,role,eligible,note,name\nnew@example.org,SLB,yes,ok,New Person\nbob@example.org,SLA,no,,\nx,SL1,yes,,\n"
        rows, errors = importers.parse_eligibility(text)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(errors), 1)
        importers.commit_eligibility(rows, self.coord, "e.csv")
        self.assertTrue(Eligibility.objects.get(user__email="new@example.org").eligible)
        self.assertFalse(Eligibility.objects.get(user=self.bob, role=self.sla).eligible)

    # ---- auth
    def test_magic_link_single_use(self):
        self.client.post(reverse("email_login"), {"email": "ALICE@example.org"})
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r"http://testserver(/login/link/\S+/)", mail.outbox[0].body).group(1)
        self.assertEqual(self.client.get(link).status_code, 200)
        self.assertRedirects(self.client.post(link), reverse("calendar"), fetch_redirect_response=False)
        self.client.logout()
        self.client.post(link)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_magic_link_unknown_email_sends_nothing(self):
        self.client.post(reverse("email_login"), {"email": "nobody@example.org"})
        self.assertEqual(len(mail.outbox), 0)

    # ---- pages
    def test_pages_render(self):
        self.client.force_login(self.coord)
        S.set_availability(self.alice, self.sl1, [D("2027-06-01")], "preferred", "morning only")
        for url in [reverse("calendar") + "?m=2027-06", reverse("day", args=["2027-06-01"]),
                    reverse("print_month", args=["2027-06"]), reverse("me"), reverse("availability"),
                    reverse("coverage") + f"?role={self.sl1.id}&m=2027-06", reverse("eligibility"),
                    reverse("import_shifters"), reverse("totals"), reverse("export_assignments"),
                    reverse("export_availability")]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.client.force_login(self.alice)
        for url in [reverse("calendar"), reverse("availability"), reverse("me")]:
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_coordinator_pages_forbidden_for_users(self):
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse("coverage")).status_code, 403)

    def test_assign_range_preview_and_confirm(self):
        self.client.force_login(self.coord)
        data = {"role": self.sl1.id, "user": self.alice.id, "start": "2027-06-07", "end": "2027-06-11", "flag": "none"}
        r = self.client.post(reverse("assign_range"), data)
        self.assertContains(r, "Confirm assignment")
        self.assertEqual(Assignment.objects.count(), 0)
        self.client.post(reverse("assign_range"), {**data, "confirm": "1"})
        self.assertEqual(Assignment.objects.filter(user=self.alice).count(), 5)
