from .base import *  # noqa: F403

DEBUG = False
if not ALLOWED_HOSTS:  # noqa: F405
    raise RuntimeError("ALLOWED_HOSTS must list the live domains (e.g. example.com,admin.example.com)")
if len(SECRET_KEY) < 50 or SECRET_KEY.startswith("change-me"):  # noqa: F405
    raise RuntimeError("SECRET_KEY must be a long random value from the host's secret store")
if FIELD_ENCRYPTION_KEY == SECRET_KEY:  # noqa: F405
    # provider keys in the database are encrypted with it; its own value lets SECRET_KEY rotate safely
    raise RuntimeError("FIELD_ENCRYPTION_KEY must be set (its own long random value, kept with the backups' secrets)")

# HTTPS is ended by the reverse proxy (deploy/Caddyfile or the host's load balancer)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SECURE_REDIRECT_EXEMPT = [r"^healthz/$"]  # container health checks speak plain http inside the network
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])  # noqa: F405
X_FRAME_OPTIONS = "DENY"
USE_X_FORWARDED_HOST = False
CONN_MAX_AGE = env.int("CONN_MAX_AGE", default=60)  # noqa: F405 — persistent DB connections per worker
CONN_HEALTH_CHECKS = True
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
