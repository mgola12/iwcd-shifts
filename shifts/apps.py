from django.apps import AppConfig


class ShiftsConfig(AppConfig):
    name = "shifts"
    verbose_name = "IWCD shifts"

    def ready(self):
        from django.contrib.auth.signals import user_logged_in

        def _log_login(sender, request, user, **kwargs):
            backend = getattr(user, "backend", "") or ""
            if "saml" in backend.lower():
                from .models import audit
                audit(user, "login", subject_user=user, note="Hyper-K SSO")

        user_logged_in.connect(_log_login, dispatch_uid="iwcd_log_login")
