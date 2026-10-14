"""SEED texts for account emails (Phase 1). Stored in EmailTemplate and edited in Super Admin afterwards."""

P = "<p>{}</p>"

SEED_TEMPLATES = [
    (
        "account/email/password_reset_key",
        "Password reset",
        "Reset your {{ platform_name }} password",
        P.format("Hello,")
        + P.format("We received a request to reset the password for your {{ platform_name }} account.")
        + P.format('<a href="{{ password_reset_url }}">Reset password</a>')
        + P.format("If you did not ask for this, you can ignore this email."),
        ["platform_name", "password_reset_url", "user"],
    ),
    (
        "account/email/unknown_account",
        "Password reset (unknown email)",
        "{{ platform_name }} password reset",
        P.format("Someone asked to reset a password for this email address, but no account uses it.")
        + P.format("If this was not you, you can ignore this email."),
        ["platform_name", "email"],
    ),
    (
        "account/email/email_confirmation",
        "Confirm email address",
        "Confirm your email for {{ platform_name }}",
        P.format("Please confirm your email address for {{ platform_name }}.")
        + P.format('<a href="{{ activate_url }}">Confirm email</a>'),
        ["platform_name", "activate_url", "user"],
    ),
    (
        "account/email/email_confirmation_signup",
        "Confirm email address (new account)",
        "Welcome to {{ platform_name }} — confirm your email",
        P.format("Welcome to {{ platform_name }}!") + P.format('<a href="{{ activate_url }}">Confirm your email</a>'),
        ["platform_name", "activate_url", "user"],
    ),
    (
        "account/email/password_changed",
        "Password changed (security alert)",
        "Your {{ platform_name }} password changed",
        P.format("The password of your {{ platform_name }} account was changed.")
        + P.format("If this was not you, reset your password immediately and contact support."),
        ["platform_name", "user"],
    ),
    (
        "account/email/password_set",
        "Password set (security alert)",
        "A password was set on your {{ platform_name }} account",
        P.format("A password was set on your {{ platform_name }} account."),
        ["platform_name", "user"],
    ),
    (
        "account/email/email_changed",
        "Email changed (security alert)",
        "Your {{ platform_name }} email changed",
        P.format("The email address of your {{ platform_name }} account was changed."),
        ["platform_name", "user"],
    ),
    (
        "mfa/email/totp_activated",
        "2FA turned on (security alert)",
        "Two-factor authentication is on",
        P.format("Two-factor authentication was turned on for your {{ platform_name }} account."),
        ["platform_name", "user"],
    ),
    (
        "mfa/email/totp_deactivated",
        "2FA turned off (security alert)",
        "Two-factor authentication was turned off",
        P.format("Two-factor authentication was turned off for your {{ platform_name }} account.")
        + P.format("If this was not you, contact support immediately."),
        ["platform_name", "user"],
    ),
    (
        "mfa/email/recovery_codes_generated",
        "New recovery codes (security alert)",
        "New 2FA recovery codes generated",
        P.format("New two-factor recovery codes were generated for your {{ platform_name }} account."),
        ["platform_name", "user"],
    ),
]
