from .base import *  # noqa: F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]  # fast hashing for tests only
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
