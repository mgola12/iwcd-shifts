from django.urls import path

from . import views as v

urlpatterns = [
    path("", v.home, name="home"),
    path("login/email/", v.email_login, name="email_login"),
    path("login/link/<str:token>/", v.magic, name="magic"),
    path("logout/", v.logout_view, name="logout"),
    path("calendar/", v.calendar_view, name="calendar"),
    path("day/<str:day>/", v.day_view, name="day"),
    path("print/<str:ym>/", v.print_month, name="print_month"),
    path("availability/", v.availability_view, name="availability"),
    path("availability/toggle/", v.availability_toggle, name="availability_toggle"),
    path("availability/range/", v.availability_range, name="availability_range"),
    path("me/", v.me_view, name="me"),
    path("me/shifts.csv", v.me_csv, name="me_csv"),
    path("me/withdraw/<int:pk>/", v.withdraw, name="withdraw"),
    path("coord/coverage/", v.coverage_view, name="coverage"),
    path("coord/assign/", v.assign_range, name="assign_range"),
    path("coord/assign-day/", v.assign_day, name="assign_day"),
    path("coord/unassign/<int:pk>/", v.unassign_one, name="unassign_one"),
    path("coord/unassign-range/", v.unassign_range, name="unassign_range"),
    path("coord/eligibility/", v.eligibility_view, name="eligibility"),
    path("coord/import-shifters/", v.import_shifters_view, name="import_shifters"),
    path("coord/totals/", v.totals_view, name="totals"),
    path("coord/export/assignments.csv", v.export_assignments, name="export_assignments"),
    path("coord/export/availability.csv", v.export_availability, name="export_availability"),
]
