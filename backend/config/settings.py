import os
import sys
from pathlib import Path
from typing import NamedTuple

import dj_database_url
import django_stubs_ext
from django.core.exceptions import ImproperlyConfigured

# Required for generic model support under django-stubs. Must run before any
# model class is defined.
django_stubs_ext.monkeypatch()

BASE_DIR = Path(__file__).resolve().parent.parent

DEBUG = os.environ.get("DEBUG", "true").lower() in ("true", "1", "yes")

if DEBUG:
    SECRET_KEY = os.environ.get("SECRET_KEY", "insecure-dev-key-change-me")
else:
    SECRET_KEY = os.environ["SECRET_KEY"].strip()  # crash if missing in production

# Commit the running build was made from. Railway auto-injects this for
# GitHub-triggered deploys; the Dockerfile also forwards it into the frontend
# build, which stamps it into SvelteKit's public /_app/version.json. Empty
# outside Railway. Read once here so the Sentry release and /api/version can't
# disagree about what's deployed.
GIT_COMMIT_SHA = os.environ.get("RAILWAY_GIT_COMMIT_SHA", "").strip()

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if h.strip()
]
# SSR and health-check traffic reaches Django on 127.0.0.1 inside the
# container, so localhost must always be allowed regardless of the env var.
for _host in ("localhost", "127.0.0.1"):
    if _host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_host)

# Railway injects RAILWAY_PUBLIC_DOMAIN as the service's `*.up.railway.app`
# host. Allow it: once the apex is fronted by the Bunny edge cache, the pull
# zone forwards the *origin* host (not the client host), so requests reaching
# Django through Bunny arrive with this Host. Unset off-Railway, so dev/CI are
# unaffected.
_railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
if _railway_domain and _railway_domain not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_railway_domain)

INSTALLED_APPS = [
    "apps.core.admin_apps.FlipAdminConfig",  # replaces "django.contrib.admin" — disables admin password login
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "config",
    "apps.accounts",
    "apps.actors",
    "apps.core",
    "apps.catalog",
    "apps.claim_edit",
    "apps.claim_ingest",
    "apps.citation",
    "apps.provenance",
    "apps.media",
    "apps.kiosk",
    "constance",
    "constance.backends.database",
]

MIDDLEWARE = [
    "django.middleware.gzip.GZipMiddleware",
    "django.middleware.http.ConditionalGetMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    # Must follow CsrfViewMiddleware: that middleware's process_request
    # populates CSRF_COOKIE, which NinjaCsrfMiddleware then validates against
    # the submitted token for unsafe-method /api/ requests.
    "apps.core.middleware.NinjaCsrfMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.SentryScopeMiddleware",
    "apps.accounts.middleware.LastSeenAtMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.KioskDisplayPolicyMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database: Postgres via DATABASE_URL, SQLite fallback for dev
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    ),
}

# Server-side cache: file-based so all gunicorn workers + management commands
# share the same cache via the filesystem. Invalidated explicitly on data changes.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": BASE_DIR / "cache",
    }
}

AUTH_USER_MODEL = "accounts.User"

# Suppressed deploy checks. Document the *why* for each entry so the
# next reader can tell "deliberately disabled" from "we forgot."
SILENCED_SYSTEM_CHECKS = [
    # User.email is USERNAME_FIELD without unique=True. Uniqueness is
    # enforced case-insensitively via the Lower("email") UniqueConstraint
    # on the User model; adding unique=True would layer on a redundant
    # case-sensitive one.
    "auth.W004",
    # SECURE_SSL_REDIRECT — Django-side HTTPS redirect. Not needed and
    # actively harmful in our topology: Railway terminates TLS at its
    # edge and only serves the domains over HTTPS externally, so Django
    # never sees an HTTP request from a real client. The only HTTP
    # traffic Django sees is Caddy → loopback, which we don't want to
    # redirect. Enabling this without SECURE_PROXY_SSL_HEADER would
    # cause an infinite redirect loop. See docs/Hosting.md.
    "security.W008",
    # HSTS family (W004 SECONDS, W005 INCLUDE_SUBDOMAINS, W021 PRELOAD)
    # — HSTS is emitted by Caddy, not Django (Django sees plaintext
    # loopback from Caddy, so SecurityMiddleware's is_secure() gate
    # would suppress the header anyway). See docs/Hosting.md § HSTS.
    "security.W004",
    "security.W005",
    "security.W021",
]

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

# ── Media storage (S3-compatible file storage provider) ───────────
MEDIA_PUBLIC_BASE_URL = os.environ.get("MEDIA_PUBLIC_BASE_URL", "/media/").strip()
if not MEDIA_PUBLIC_BASE_URL.endswith("/"):
    raise ImproperlyConfigured(
        f"MEDIA_PUBLIC_BASE_URL must end with a slash (got {MEDIA_PUBLIC_BASE_URL!r})."
    )
MEDIA_URL = MEDIA_PUBLIC_BASE_URL

if os.environ.get("MEDIA_STORAGE_BUCKET"):
    STORAGES["default"] = {
        "BACKEND": "storages.backends.s3boto3.S3Boto3Storage",
    }
    AWS_STORAGE_BUCKET_NAME = os.environ["MEDIA_STORAGE_BUCKET"].strip()
    AWS_S3_REGION_NAME = os.environ.get("MEDIA_STORAGE_REGION", "auto").strip()
    AWS_S3_ENDPOINT_URL = os.environ["MEDIA_STORAGE_ENDPOINT"].strip()
    AWS_ACCESS_KEY_ID = os.environ["MEDIA_STORAGE_ACCESS_KEY"].strip()
    AWS_SECRET_ACCESS_KEY = os.environ["MEDIA_STORAGE_SECRET_KEY"].strip()
    # Storage keys are UUID-derived and write-once, so renditions are
    # immutable once written. `immutable` tells browsers to skip
    # revalidation entirely, not just honor max-age.
    AWS_S3_OBJECT_PARAMETERS = {
        "CacheControl": "public, max-age=31536000, immutable",
    }
else:
    STORAGES["default"] = {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    }
    MEDIA_ROOT = BASE_DIR / "media"

# Allow large image uploads (20MB) to reach our view for proper error
# messages. FILE_UPLOAD_MAX_MEMORY_SIZE stays at default (2.5MB) — larger
# files spill to disk temp files, which is fine.
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024  # 25 MB

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django.request": {
            "level": "ERROR",
        },
        "django.db.backends": {
            "level": "WARNING",
        },
    },
}

# ── Signup (onboarding) ───────────────────────────────────────────
# Where to send a user who clicks "Not you?" on /signup after detaching
# from WorkOS. Must be reachable unauthenticated AND must not redirect
# to sign-in — landing the user back at the IdP after they just rejected
# their identity is a near-guaranteed re-auth with the same wrong account.
SIGNUP_CANCEL_RETURN_URL = os.environ.get("SIGNUP_CANCEL_RETURN_URL", "/").strip()

# Pre-auth rate limits — buckets are keyed by session id / client IP
# rather than user pk because there's no User yet. Two parallel buckets
# (session + IP) per endpoint: session catches a single tab spamming;
# IP catches a scraper rotating cookies but not addresses.
#
# Budgets are per-minute. Justification:
# - check: ~250ms debounce × ~10 chars ≈ 5–10 checks per real session.
#   60/min/session is generous headroom; 300/min/IP catches scrapers
#   without breaking shared NATs (coffee shop, school).
# - submit: real users submit once or twice (one retry on a collision).
#   10/min/session, 30/min/IP.
# - cancel: IP-only — a session-key limit would just catch the "user
#   click-spams the link" case and force a carve-out around
#   ensure_session_key. The IP cap is what actually deters abuse.
SIGNUP_CHECK_RATELIMIT_SESSION = (60, 60)  # (limit, window_seconds)
SIGNUP_CHECK_RATELIMIT_IP = (300, 60)
SIGNUP_SUBMIT_RATELIMIT_SESSION = (10, 60)
SIGNUP_SUBMIT_RATELIMIT_IP = (30, 60)
SIGNUP_CANCEL_RATELIMIT_IP = (20, 60)

# Public bulk-export API (GET /api/export/<entity>/). One shared per-IP bucket
# across all 20 export endpoints, so the limit is a per-IP full-sync budget: a
# full dump is ~20 requests, so 120/hour ≈ 6 full dumps/hour. Generous for batch
# consumers (who should save the export and work locally) while capping the
# real-time polling the export exists to discourage. (limit, window_seconds).
EXPORT_RATELIMIT_IP = (120, 3600)

# ── WorkOS AuthKit ────────────────────────────────────────────────
WORKOS_API_KEY = os.environ.get("WORKOS_API_KEY", "").strip()
WORKOS_CLIENT_ID = os.environ.get("WORKOS_CLIENT_ID", "").strip()
WORKOS_REDIRECT_URI = os.environ.get(
    "WORKOS_REDIRECT_URI", "http://localhost:5173/api/auth/callback/"
).strip()

AUTHENTICATION_BACKENDS = [
    "apps.accounts.backends.WorkOSBackend",
    "django.contrib.auth.backends.ModelBackend",  # Django admin password login
]

# ── Rate limiting ────────────────────────────────────────────────
# Gate for trusting proxy-supplied client-IP headers in
# ``apps.core.rate_limits._client_ip``. Default False so dev, tests, and
# any unsanitized container key off REMOTE_ADDR. Production sets this to
# True, asserting that Caddy has stripped Forwarded and that X-Real-IP
# was populated by Railway's edge.
RATE_LIMIT_TRUST_PROXY_HEADERS = os.environ.get(
    "RATE_LIMIT_TRUST_PROXY_HEADERS", "false"
).lower() in ("true", "1", "yes")

# ── Sessions ─────────────────────────────────────────────────────
SESSION_COOKIE_AGE = 60 * 60 * 24 * 90  # 90 days
SESSION_SAVE_EVERY_REQUEST = True  # sliding window — reset expiry on each request

# CSRF — allow JS to read the cookie for X-CSRFToken header
CSRF_COOKIE_HTTPONLY = False
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("CSRF_TRUSTED_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]

# Secure cookies in production
if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SAMESITE = "Lax"
    # TLS is terminated by Railway's edge proxy and (in the container) by
    # Caddy.  Django never receives external traffic directly, so SSL
    # redirect and proxy-header sniffing are unnecessary.  Keeping them
    # would break internal callers (SSR, health checks) that reach Django
    # over plain HTTP on 127.0.0.1.

# ---------------------------------------------------------------------------
# Constance (runtime-configurable settings)
# ---------------------------------------------------------------------------
CONSTANCE_BACKEND = "constance.backends.database.DatabaseBackend"
if "pytest" in sys.modules:
    CONSTANCE_BACKEND = "constance.backends.memory.MemoryBackend"

DISPLAY_POLICY_CHOICES = (
    ("show-all", "☠️ Show All Content — includes Not Allowed (e.g. IPDB images)"),
    ("include-unknown", "⚠️ Include Unknown License Content (e.g. OPDB images)"),
    ("licensed-only", "✅ Show Only Licensed Content — no OPDB or IPDB images"),
)


# django-constance expects each CONSTANCE_CONFIG value to be a tuple of
# (default, help_text, field_type_or_name). It unpacks positionally, which is
# why this is a NamedTuple rather than a TypedDict.
class ConstanceSpec(NamedTuple):
    default: object
    help_text: str
    field: type | str


CONSTANCE_CONFIG: dict[str, ConstanceSpec] = {
    "CONTENT_DISPLAY_POLICY": ConstanceSpec(
        default="licensed-only",
        help_text="Controls which content is shown based on license status",
        field=str,
    ),
}

CONSTANCE_ADDITIONAL_FIELDS = {
    "display_policy_select": [
        "django.forms.fields.ChoiceField",
        {"widget": "django.forms.Select", "choices": DISPLAY_POLICY_CHOICES},
    ],
}

CONSTANCE_CONFIG["CONTENT_DISPLAY_POLICY"] = ConstanceSpec(
    default="licensed-only",
    help_text="Controls which content is shown based on license status",
    field="display_policy_select",
)

CONSTANCE_CONFIG_FIELDSETS = (("Content Display", ("CONTENT_DISPLAY_POLICY",)),)

# ---------------------------------------------------------------------------
# Sentry (error tracking)
# ---------------------------------------------------------------------------
# DSN presence is the master switch — see ObservabilityArchitecture.md §
# Environment separation. Local, CI, and test environments leave SENTRY_DSN
# unset; production sets it via Railway. There is no per-environment matrix
# and no runtime kill switch.
SENTRY_DSN = os.environ.get("SENTRY_DSN", "").strip()
if SENTRY_DSN:
    # Imports gated on the DSN so local dev, CI, and tests pay no
    # import cost (sentry-sdk is non-trivial). The empty-DSN guard
    # is the master switch — keeping imports on the same side of
    # it makes "no DSN, no Sentry" hold at module load too, not
    # just at init time.
    import logging

    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.scrubber import EventScrubber

    from config.sentry_options import IGNORE_ERRORS

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment="production",
        release=GIT_COMMIT_SHA,
        send_default_pii=False,
        # Drop request bodies entirely. With ``"never"`` the SDK does
        # not extract POST/PATCH payloads at all, replacing them with
        # an over-size-limit marker.
        max_request_body_size="never",
        traces_sample_rate=0.0,
        profiles_sample_rate=0.0,
        # Implements ObservabilityArchitecture.md § Capture scope's
        # "don't capture" list. ``DjangoIntegration`` hooks
        # ``got_request_exception``, which fires for these classes
        # before Django's resolve_exception_handler maps them to 4xx
        # responses — without this filter they'd flood the issue
        # stream. ``StructuredApiError`` covers rate-limit denials
        # and other structured 4xx errors raised through Ninja.
        ignore_errors=IGNORE_ERRORS,
        # Crash-free request rate per release. Cheap signal; works
        # without tracing. ``True`` is the SDK default in 2.x; set
        # explicitly to pin the behavior in case Sentry ever changes it.
        auto_session_tracking=True,
        # Default flush window is 2s; 5s gives the SDK enough time
        # to drain queued events on a SIGTERM (Railway deploys,
        # rolling restarts) without delaying graceful shutdown.
        shutdown_timeout=5,
        integrations=[
            DjangoIntegration(),
            # Log records become breadcrumbs but never standalone events;
            # Logs and error events are decoupled.
            LoggingIntegration(level=logging.INFO, event_level=None),
        ],
        # Override the auto-instantiated EventScrubber to enable
        # recursive descent into nested dicts and lists. The default
        # is shallow, which would miss sensitive keys buried in
        # nested ``extra`` / ``contexts`` / breadcrumb-data payloads.
        # ``send_default_pii=False`` flows through so the PII denylist
        # (REMOTE_ADDR, X-Forwarded-For, etc.) is merged in.
        #
        # Email / IP pattern masking and ``request.query_string`` drop
        # are handled by server-side Advanced Data Scrubbing rules
        # (see ObservabilityArchitecture.md § Privacy enforcement).
        event_scrubber=EventScrubber(recursive=True, send_default_pii=False),
    )
