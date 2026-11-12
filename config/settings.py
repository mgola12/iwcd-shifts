"""Settings for iwcd-shifts. All site-specific values come from .env."""
import os
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent
env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env")

DEBUG = env.bool("DEBUG", default=False)
SECRET_KEY = env("SECRET_KEY", default="dev-only-insecure-key" if DEBUG else environ.Env.NOTSET)
BASE_URL = env("BASE_URL", default="https://iwcd-shifts.hyperk.ca").rstrip("/")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["iwcd-shifts.hyperk.ca", "localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = [BASE_URL]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "djangosaml2",
    "shifts",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "djangosaml2.middleware.SamlSessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "shifts.context_processors.site",
            ],
        },
    },
]

DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'data' / 'db.sqlite3'}"),
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "shifts.User"

AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "shifts.saml_backend.HyperKSaml2Backend",
]
LOGIN_URL = "home"
LOGIN_REDIRECT_URL = "calendar"
LOGOUT_REDIRECT_URL = "home"

LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Asia/Tokyo"  # all shift times are JST
USE_I18N = False
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# Security (behind HTTPS reverse proxy)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14

# Email
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="IWCD Shifts <no-reply@hyperk.ca>")
SERVER_EMAIL = DEFAULT_FROM_EMAIL
COORDINATOR_EMAILS = env.list("COORDINATOR_EMAILS", default=[])

# App settings
SHIFT_HOURS = 8
SHIFT_START = "09:00"
SHIFT_END = "17:00"
MIN_BLOCK_DAYS = 5
MAGIC_LINK_ENABLED = env.bool("MAGIC_LINK_ENABLED", default=True)
MAGIC_LINK_MAX_AGE = 15 * 60
BACKUP_DIR = Path(env("BACKUP_DIR", default=str(BASE_DIR / "backups")))
BACKUP_KEEP_DAYS = 30

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {"saml2": {"level": "WARNING"}, "djangosaml2": {"level": "INFO"}},
}

# ---------------------------------------------------------------------------
# Hyper-K SAML 2.0 SSO (HKDB IdP, https://hkdbweb.in2p3.fr)
# ---------------------------------------------------------------------------
SAML_ENABLED = env.bool("SAML_ENABLED", default=True)
SAML_DIR = Path(env("SAML_DIR", default=str(BASE_DIR / "saml")))
SAML_IDP_METADATA_URL = env("SAML_IDP_METADATA_URL", default="https://hkdbweb.in2p3.fr/saml20-metadata.xml")
SAML_IDP_METADATA_FILE = SAML_DIR / "idp-metadata.xml"

SAML_SESSION_COOKIE_NAME = "saml_session"
SAML_SESSION_COOKIE_SAMESITE = "None"
SAML_DJANGO_USER_MAIN_ATTRIBUTE = "email"
SAML_DJANGO_USER_MAIN_ATTRIBUTE_LOOKUP = "__iexact"
SAML_USE_NAME_ID_AS_USERNAME = False
SAML_CREATE_UNKNOWN_USER = True
ACS_DEFAULT_REDIRECT_URL = "/calendar/"
SAML_IGNORE_LOGOUT_ERRORS = True

# Attributes arrive as urn:oid names; pysaml2 converts them to friendly names.
# Both forms are listed so the mapping works either way.
SAML_ATTRIBUTE_MAPPING = {
    "mail": ("email",),
    "urn:oid:0.9.2342.19200300.100.1.3": ("email",),
    "givenName": ("first_name",),
    "urn:oid:2.5.4.42": ("first_name",),
    "sn": ("last_name",),
    "urn:oid:2.5.4.4": ("last_name",),
    "eduPersonPrincipalName": ("eppn",),
    "urn:oid:1.3.6.1.4.1.5923.1.1.1.6": ("eppn",),
    "displayName": ("display_name",),
    "urn:oid:2.16.840.1.113730.3.1.241": ("display_name",),
    "schacHomeOrganization": ("institution",),
    "urn:oid:1.3.6.1.4.1.25178.1.2.9": ("institution",),
}

if SAML_ENABLED:
    import saml2
    import saml2.saml
    import saml2.xmldsig

    _idp_metadata = (
        {"local": [str(SAML_IDP_METADATA_FILE)]}
        if SAML_IDP_METADATA_FILE.exists()
        else {"remote": [{"url": SAML_IDP_METADATA_URL}]}
    )
    _contact = []
    if env("SAML_CONTACT_EMAIL", default=""):
        _contact = [{
            "given_name": env("SAML_CONTACT_NAME", default="IWCD Shifts admin"),
            "email_address": env("SAML_CONTACT_EMAIL"),
            "contact_type": "technical",
        }]

    SAML_CONFIG = {
        "xmlsec_binary": env("XMLSEC_BINARY", default="/usr/bin/xmlsec1"),
        "entityid": f"{BASE_URL}/saml/metadata/",
        "attribute_map_dir": os.path.join(os.path.dirname(saml2.__file__), "attributemaps"),
        "allow_unknown_attributes": True,
        "service": {
            "sp": {
                "name": "IWCD Shifts",
                "name_id_format": saml2.saml.NAMEID_FORMAT_EMAILADDRESS,
                "endpoints": {
                    "assertion_consumer_service": [
                        (f"{BASE_URL}/saml/acs/", saml2.BINDING_HTTP_POST),
                    ],
                    "single_logout_service": [
                        (f"{BASE_URL}/saml/sls/", saml2.BINDING_HTTP_REDIRECT),
                        (f"{BASE_URL}/saml/sls/", saml2.BINDING_HTTP_POST),
                    ],
                },
                "authn_requests_signed": True,
                "logout_requests_signed": True,
                "want_response_signed": env.bool("SAML_WANT_RESPONSE_SIGNED", default=False),
                "want_assertions_signed": env.bool("SAML_WANT_ASSERTIONS_SIGNED", default=True),
                "allow_unsolicited": env.bool("SAML_ALLOW_UNSOLICITED", default=False),
                "signing_algorithm": saml2.xmldsig.SIG_RSA_SHA256,
                "digest_algorithm": saml2.xmldsig.DIGEST_SHA256,
                "required_attributes": ["mail", "givenName", "sn", "eduPersonPrincipalName"],
                "optional_attributes": ["displayName", "cn", "schacHomeOrganization"],
            },
        },
        "metadata": _idp_metadata,
        "debug": DEBUG,
        "key_file": str(SAML_DIR / "sp.key"),
        "cert_file": str(SAML_DIR / "sp.crt"),
        "encryption_keypairs": [
            {"key_file": str(SAML_DIR / "sp.key"), "cert_file": str(SAML_DIR / "sp.crt")},
        ],
        "contact_person": _contact,
        "organization": {
            "name": [("Hyper-Kamiokande IWCD", "en")],
            "display_name": [("IWCD Shifts", "en")],
            "url": [(BASE_URL, "en")],
        },
    }
