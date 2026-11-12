from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import BaseUserCreationForm, UserChangeForm

from .models import (Assignment, AuditLog, Availability, ClosedDay, Eligibility, Phase, Role,
                     ShiftImport, Subsystem, User)


class UserCreateForm(BaseUserCreationForm):
    class Meta:
        model = User
        fields = ("email", "first_name", "last_name")


class UserEditForm(UserChangeForm):
    class Meta:
        model = User
        fields = "__all__"


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserEditForm
    add_form = UserCreateForm
    ordering = ["last_name", "first_name"]
    list_display = ["email", "first_name", "last_name", "institution", "is_staff", "last_login"]
    list_filter = ["is_staff", "is_active", "institution"]
    search_fields = ["email", "first_name", "last_name", "display_name", "eppn", "institution"]
    fieldsets = [
        (None, {"fields": ["email", "password"]}),
        ("Profile", {"fields": ["first_name", "last_name", "display_name", "institution", "eppn"]}),
        ("Permissions", {"fields": ["is_active", "is_staff", "is_superuser", "groups", "user_permissions"]}),
        ("Dates", {"fields": ["last_login", "date_joined"]}),
    ]
    add_fieldsets = [(None, {"classes": ["wide"], "fields": ["email", "first_name", "last_name", "password1", "password2"]})]


class RoleInline(admin.TabularInline):
    model = Role
    extra = 0


@admin.register(Phase)
class PhaseAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "subsystem", "start_date", "end_date"]
    inlines = [RoleInline]


admin.site.register(Subsystem)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "phase", "slots_per_day", "self_service"]
    list_filter = ["phase"]


@admin.register(ClosedDay)
class ClosedDayAdmin(admin.ModelAdmin):
    list_display = ["date", "reason"]
    date_hierarchy = "date"


@admin.register(Eligibility)
class EligibilityAdmin(admin.ModelAdmin):
    list_display = ["user", "role", "eligible", "confirmed_on", "tutorials_done", "site_safety_done", "onboarding_done", "note"]
    list_filter = ["role", "eligible", "tutorials_done", "site_safety_done", "onboarding_done"]
    list_editable = ["eligible", "tutorials_done", "site_safety_done", "onboarding_done"]
    search_fields = ["user__email", "user__last_name", "user__first_name"]
    autocomplete_fields = ["user"]


@admin.register(Availability)
class AvailabilityAdmin(admin.ModelAdmin):
    list_display = ["date", "role", "user", "state", "comment"]
    list_filter = ["role", "state"]
    date_hierarchy = "date"
    search_fields = ["user__email", "user__last_name"]


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ["date", "role", "user", "flag", "source", "reminded_t7", "reminded_t1"]
    list_filter = ["role", "flag", "source"]
    date_hierarchy = "date"
    search_fields = ["user__email", "user__last_name"]
    autocomplete_fields = ["user"]


@admin.register(ShiftImport)
class ShiftImportAdmin(admin.ModelAdmin):
    list_display = ["ts", "kind", "file_name", "rows_loaded", "date_range_start", "date_range_end", "admin"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["ts", "actor", "verb", "subject_user", "role", "date", "note"]
    list_filter = ["verb", "role"]
    search_fields = ["actor__email", "subject_user__email", "note"]
    date_hierarchy = "ts"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
