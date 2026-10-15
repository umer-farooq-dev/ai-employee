"""Settings shared by every environment.

Only infrastructure values come from the environment (.env locally, the host's secret store in production).
Business values (names, limits, policies, prices, texts, provider keys) live in the database and are edited in
Super Admin — see apps.platform_config.
"""

from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
env = environ.Env()
environ.Env.read_env(BASE_DIR.parent / ".env")

SECRET_KEY = env("SECRET_KEY")
FIELD_ENCRYPTION_KEY = env("FIELD_ENCRYPTION_KEY", default=SECRET_KEY)  # master key for encrypted DB fields
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])
# Super Admin on its own host so staff and company / website sessions never share a cookie (empty = same host).
ADMIN_HOST = env("ADMIN_HOST", default="")
ENVIRONMENT = env("ENVIRONMENT", default="local")  # local | staging | production

INSTALLED_APPS = [
    # django.contrib.admin is intentionally NOT installed (decision D9: custom Super Admin only)
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "rest_framework",
    "drf_spectacular",
    "allauth",
    "allauth.account",
    "allauth.mfa",
    "allauth.usersessions",
    "allauth.headless",
    "apps.core",
    "apps.accounts",
    "apps.audit",
    "apps.rbac",
    "apps.tenancy",
    "apps.platform_config",
    "apps.billing",
    "apps.industries",
    "apps.roles_tools",
    "apps.crm",
    "apps.catalog",
    "apps.scheduling",
    "apps.cms",
    "apps.notifications",
    "apps.superadmin",
    "apps.api",
    "apps.website",
    "apps.panel",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.request.RequestContextMiddleware",
    "apps.accounts.middleware.AdminHostMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "allauth.usersessions.middleware.UserSessionsMiddleware",
    "apps.accounts.middleware.SessionSecurityMiddleware",
    "apps.tenancy.middleware.TenantMiddleware",
    "apps.accounts.middleware.AdminIPAllowlistMiddleware",
    "apps.accounts.middleware.Require2FAMiddleware",
    "apps.accounts.middleware.TimezoneMiddleware",
    "apps.accounts.middleware.MaintenanceMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

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
                "apps.platform_config.context_processors.platform",
            ],
        },
    },
]

DATABASES = {"default": env.db("DATABASE_URL")}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {"default": env.cache("REDIS_URL", default="locmemcache://")}

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "apps.accounts.validators.SettingsMinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

# django-allauth: email login, no usernames, verified email, editable emails, encrypted 2FA secrets
ACCOUNT_ADAPTER = "apps.accounts.adapter.AccountAdapter"
MFA_ADAPTER = "apps.accounts.adapter.MFAAdapter"
ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "password1*", "password2*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD = None
# Email verification is read from Super Admin → System Settings → Registration (apps/accounts/allauth_settings.py).
ACCOUNT_SIGNUP_FORM_CLASS = "apps.accounts.forms.CompanySignupForm"
ACCOUNT_LOGOUT_ON_GET = False
ACCOUNT_SESSION_REMEMBER = None  # "Remember me" checkbox on the login form
ACCOUNT_EMAIL_NOTIFICATIONS = True  # security alerts: password / email changed
ACCOUNT_EMAIL_SUBJECT_PREFIX = ""
MFA_SUPPORTED_TYPES = ["totp", "recovery_codes"]
USERSESSIONS_TRACK_ACTIVITY = True
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "panel:home"

# allauth headless = the login / 2FA / password API for the future Flutter app (API-02): Bearer JWT tokens
HEADLESS_CLIENTS = ("browser", "app")
HEADLESS_ONLY = False
HEADLESS_TOKEN_STRATEGY = (
    "allauth.headless.tokens.strategies.jwt.JWTTokenStrategy"  # nosec B105 (class path, not a secret)
)
HEADLESS_JWT_ALGORITHM = "HS256"
HEADLESS_JWT_PRIVATE_KEY = env("JWT_SIGNING_KEY", default=SECRET_KEY)
HEADLESS_JWT_ACCESS_TOKEN_EXPIRES_IN = env.int("JWT_ACCESS_SECONDS", default=300)
HEADLESS_JWT_REFRESH_TOKEN_EXPIRES_IN = env.int("JWT_REFRESH_SECONDS", default=86400)
HEADLESS_SERVE_SPECIFICATION = True

FORMS_URLFIELD_ASSUME_HTTPS = True
LANGUAGE_CODE = "en-in"
TIME_ZONE = "UTC"  # storage; the display timezone is activated per request from settings / user / company
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR.parent / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR.parent / "media"  # public files: logos, avatars, website images
PRIVATE_MEDIA_ROOT = BASE_DIR.parent / "private_media"  # company files, served only via signed URLs (TEN-03)

EMAIL_CONFIG = env.email_url("EMAIL_URL", default="smtp://127.0.0.1:1025")
vars().update(EMAIL_CONFIG)

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "allauth.headless.contrib.rest_framework.authentication.JWTTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "apps.api.pagination.CursorPagination",
    "DEFAULT_THROTTLE_CLASSES": [
        "apps.api.throttling.UserRateThrottle",
        "apps.api.throttling.AnonRateThrottle",
        "apps.api.throttling.CompanyRateThrottle",
    ],
    "EXCEPTION_HANDLER": "apps.api.errors.exception_handler",
}
SPECTACULAR_SETTINGS = {
    "TITLE": "AI Employee API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": r"/(api|public)/v1",
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "apps.audit.logging.JsonFormatter"}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "json"},
        "database": {"class": "apps.audit.logging.DatabaseErrorHandler", "level": "ERROR"},
    },
    "root": {"handlers": ["console", "database"], "level": env("LOG_LEVEL", default="INFO")},
}

# Error tracking (ENGR-05): enabled when the hosting provides a Sentry DSN.
if env("SENTRY_DSN", default=""):
    import sentry_sdk

    sentry_sdk.init(dsn=env("SENTRY_DSN"), environment=ENVIRONMENT, send_default_pii=False)
