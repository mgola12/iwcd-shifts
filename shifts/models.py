from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra["is_staff"] = True
        extra["is_superuser"] = True
        return self._create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """A collaborator. Email is the login key (matches HKDB 'mail' and the shifter CSV)."""

    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    display_name = models.CharField(max_length=200, blank=True)
    institution = models.CharField(max_length=200, blank=True)
    eppn = models.CharField("eduPersonPrincipalName", max_length=255, blank=True, db_index=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField("coordinator / admin", default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["last_name", "first_name", "email"]

    def save(self, *args, **kwargs):
        self.email = (self.email or "").strip().lower()
        super().save(*args, **kwargs)

    @property
    def name(self):
        return self.display_name or f"{self.first_name} {self.last_name}".strip() or self.email

    def get_full_name(self):
        return self.name

    def get_short_name(self):
        return self.first_name or self.name

    def __str__(self):
        return self.name


class Subsystem(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=200)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Phase(models.Model):
    subsystem = models.ForeignKey(Subsystem, on_delete=models.PROTECT, related_name="phases")
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=200)
    start_date = models.DateField()
    end_date = models.DateField()
    manual_url = models.URLField(blank=True)
    color = models.CharField(max_length=7, default="#0d6efd")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["start_date", "order"]
        unique_together = [("subsystem", "code")]

    def contains(self, day):
        return self.start_date <= day <= self.end_date

    def __str__(self):
        return self.name


class Role(models.Model):
    """A slot type within a phase (SL1, SLA, SLB, SHIFTER...). Data, not code."""

    SHIFTER = "SHIFTER"

    phase = models.ForeignKey(Phase, on_delete=models.CASCADE, related_name="roles")
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    slots_per_day = models.PositiveSmallIntegerField(default=1)
    self_service = models.BooleanField(
        default=True, help_text="Eligible people can enter availability. False for imported shifters."
    )
    color = models.CharField(max_length=7, default="#6f42c1")
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["phase__start_date", "order", "code"]
        unique_together = [("phase", "code")]

    @property
    def is_shifter(self):
        return self.code == self.SHIFTER

    def __str__(self):
        return f"{self.name} ({self.code})"


class ClosedDay(models.Model):
    """Weekdays with no shifts (Japanese holidays, J-PARC closures)."""

    date = models.DateField(unique=True)
    reason = models.CharField(max_length=200)

    class Meta:
        ordering = ["date"]

    def __str__(self):
        return f"{self.date} {self.reason}"


class Eligibility(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="eligibilities")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="eligibilities")
    eligible = models.BooleanField(default=True)
    confirmed_on = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True)
    tutorials_done = models.BooleanField(default=False)
    site_safety_done = models.BooleanField(default=False)
    onboarding_done = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "role")]
        verbose_name_plural = "eligibilities"
        ordering = ["role", "user"]

    def __str__(self):
        return f"{self.user} - {self.role.code}: {'yes' if self.eligible else 'no'}"


class Availability(models.Model):
    PREFERRED = "preferred"
    AVAILABLE = "available"
    IF_NEEDED = "if_needed"
    STATES = [(PREFERRED, "Preferred"), (AVAILABLE, "Available"), (IF_NEEDED, "If needed")]
    STATE_ORDER = [PREFERRED, AVAILABLE, IF_NEEDED]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="availabilities")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="availabilities")
    date = models.DateField()
    state = models.CharField(max_length=12, choices=STATES, default=AVAILABLE)
    comment = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("user", "role", "date")]
        ordering = ["date"]
        verbose_name_plural = "availabilities"

    def __str__(self):
        return f"{self.user} {self.role.code} {self.date} {self.state}"


class Assignment(models.Model):
    SOURCE_ADMIN = "admin"
    SOURCE_IMPORTED = "imported"
    SOURCES = [(SOURCE_ADMIN, "Assigned by coordinator"), (SOURCE_IMPORTED, "Imported (central scheduler)")]

    FLAG_NONE = "none"
    FLAG_OVERLAP = "overlap"
    FLAG_ONBOARDING = "onboarding"
    FLAG_COVER = "cover"
    FLAGS = [
        (FLAG_NONE, "-"),
        (FLAG_OVERLAP, "Overlap (SLA hand-over)"),
        (FLAG_ONBOARDING, "Onboarding"),
        (FLAG_COVER, "Coordinator cover"),
    ]
    # Flags that do NOT fill the slot (extra person on that day).
    NON_FILLING = (FLAG_OVERLAP, FLAG_ONBOARDING)

    role = models.ForeignKey(Role, on_delete=models.PROTECT, related_name="assignments")
    date = models.DateField()
    user = models.ForeignKey(User, on_delete=models.PROTECT, related_name="assignments")
    source = models.CharField(max_length=10, choices=SOURCES, default=SOURCE_ADMIN)
    flag = models.CharField(max_length=12, choices=FLAGS, default=FLAG_NONE)
    note = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reminded_t7 = models.BooleanField(default=False)
    reminded_t1 = models.BooleanField(default=False)

    class Meta:
        unique_together = [("role", "date", "user")]
        ordering = ["date", "role__order"]

    @property
    def fills_slot(self):
        return self.flag not in self.NON_FILLING

    def __str__(self):
        return f"{self.date} {self.role.code} {self.user}"


class ShiftImport(models.Model):
    KINDS = [("shifters", "Shifters"), ("eligibility", "Eligibility")]
    ts = models.DateTimeField(auto_now_add=True)
    admin = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    kind = models.CharField(max_length=12, choices=KINDS)
    file_name = models.CharField(max_length=255)
    rows_loaded = models.PositiveIntegerField(default=0)
    date_range_start = models.DateField(null=True, blank=True)
    date_range_end = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-ts"]


class AuditLog(models.Model):
    VERBS = [
        ("availability_set", "Availability set"),
        ("availability_removed", "Availability removed"),
        ("assign", "Assigned"),
        ("unassign", "Unassigned"),
        ("withdraw", "Withdrew from assignment"),
        ("eligibility_set", "Eligibility set"),
        ("import_run", "Import run"),
        ("login", "Login"),
    ]
    ts = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    verb = models.CharField(max_length=24, choices=VERBS)
    subject_user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    role = models.ForeignKey(Role, null=True, blank=True, on_delete=models.SET_NULL)
    date = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-ts"]

    def __str__(self):
        return f"{self.ts:%Y-%m-%d %H:%M} {self.actor} {self.verb}"


def audit(actor, verb, subject_user=None, role=None, date=None, note=""):
    return AuditLog.objects.create(
        actor=actor if getattr(actor, "pk", None) else None,
        verb=verb, subject_user=subject_user, role=role, date=date, note=note[:2000],
    )
