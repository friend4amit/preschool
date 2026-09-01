"""Settings shared by every environment. Environment-specific files import * from here."""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()

# Read a local .env when one exists; in prod the values come from the container env.
if (BASE_DIR / ".env").exists():
    environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("SECRET_KEY")
DEBUG = False
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "config.apps.AarohamAdminConfig",  # superadmin-only admin site
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "django.contrib.sitemaps",
    "django_tasks",
    "django_tasks_db",
    "simple_history",
    "apps.core",
    "apps.people",
    "apps.website",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Stamps the acting user onto history rows. This is a thread-local, and the
    # non-negotiable in docs/plan.md bans thread-locals for *scoping* — for the
    # good reason that migrations, loaddata, shell sessions and background tasks
    # have no request and would silently see nothing. Attribution fails safe the
    # other way: no request means history_user is null, which is honest.
    "simple_history.middleware.HistoryRequestMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL")}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# A custom user from migration 0001 — swapping AUTH_USER_MODEL later is one of the
# few genuinely painful things to undo in Django. See docs/plan.md.
AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# India only: one timezone, everywhere, forever. No per-user timezone.
LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Parents check this occasionally from a phone; weekly re-auth is the fastest way
# to make the portal unused.
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30
SESSION_SAVE_EVERY_REQUEST = True

LOGIN_URL = "login"
# Staff and parents share one login form and belong in different consoles, so the
# redirect target is a view that asks which. See apps/core/views.py.
LOGIN_REDIRECT_URL = "after_login"

# Set-password links are handed over in person or over the school's WhatsApp group,
# not emailed, so they need to survive a weekend. Django's default is 3 days.
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24 * 7

# Cloudflare Turnstile. Cloudflare publishes always-passing test keys for dev.
TURNSTILE_SITE_KEY = env("TURNSTILE_SITE_KEY", default="")
TURNSTILE_SECRET_KEY = env("TURNSTILE_SECRET_KEY", default="")

# Where enquiry notifications go. Falls back to the branch email in SiteSettings.
ENQUIRY_NOTIFICATION_EMAIL = env("ENQUIRY_NOTIFICATION_EMAIL", default="")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@aaroham.local")

SITE_ID = 1

# --- Backups ------------------------------------------------------------------------
# Read here rather than only in prod.py so the backup service can be exercised from
# the dev stack. Without credentials the task refuses loudly instead of no-opping,
# which is the difference between "no backup" and "a backup you think you have".
R2_ACCESS_KEY_ID = env("R2_ACCESS_KEY_ID", default="")
R2_SECRET_ACCESS_KEY = env("R2_SECRET_ACCESS_KEY", default="")
R2_BUCKET = env("R2_BUCKET", default="")
R2_ENDPOINT_URL = env("R2_ENDPOINT_URL", default="")

BACKUP_PREFIX = env("BACKUP_PREFIX", default="backups/postgres/")
BACKUP_RETENTION_DAYS = env.int("BACKUP_RETENTION_DAYS", default=30)
