from django.core.exceptions import ValidationError

from apps.platform_config import services as config


class SettingsMinimumLengthValidator:
    """Password minimum length from Super Admin → Security (no hard-coded policy)."""

    def validate(self, password, user=None):
        minimum = config.get("security.password_min_length")
        if len(password) < minimum:
            raise ValidationError(
                f"This password is too short. It must contain at least {minimum} characters.", code="password_too_short"
            )

    def get_help_text(self):
        return f"Your password must contain at least {config.get('security.password_min_length')} characters."
