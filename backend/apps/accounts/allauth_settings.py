"""AUTH-02: email verification is a Super Admin setting (Registration → Email verification), not a Django setting.

allauth reads ACCOUNT_EMAIL_VERIFICATION through its AppSettings object on every use; we swap in a subclass whose
EMAIL_VERIFICATION reads the settings registry instead.
"""

from allauth.account import app_settings
from django.db import DatabaseError

from apps.platform_config.registry import BY_KEY

KEY = "registration.email_verification"


class _AppSettings(type(app_settings._app_settings)):
    @property
    def EMAIL_VERIFICATION(self):
        from apps.platform_config import services as config

        try:
            value = config.get(KEY)
        except DatabaseError:  # system checks before the first migration
            value = BY_KEY[KEY].default
        return self.EmailVerificationMethod(value)


def install():
    if not isinstance(app_settings._app_settings, _AppSettings):
        app_settings._app_settings = _AppSettings(app_settings._app_settings.prefix)
