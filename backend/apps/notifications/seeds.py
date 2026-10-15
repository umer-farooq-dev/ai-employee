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
    # Phase 2: registration, approval, team, website enquiries
    (
        "company/registered_team",
        "New company registration (to platform team)",
        "New registration: {{ company.name }}",
        P.format("A new company registered on {{ platform_name }} and is waiting for review.")
        + P.format("<b>{{ company.name }}</b> — {{ company.industry.name }}, {{ company.city }}, {{ company.state }}")
        + P.format("Owner: {{ owner.full_name }} ({{ owner.email }}, {{ owner.phone }})")
        + P.format('<a href="{{ review_url }}">Review in Super Admin</a>'),
        ["platform_name", "company", "owner", "review_url"],
    ),
    (
        "company/approved",
        "Company approved",
        "Your {{ platform_name }} account is approved",
        P.format("Good news! Your company <b>{{ company.name }}</b> has been approved.")
        + P.format("You can now sign in and set up your AI Employee.")
        + P.format('<a href="{{ login_url }}">Sign in</a>'),
        ["platform_name", "company", "login_url"],
    ),
    (
        "company/rejected",
        "Company registration not approved",
        "Your {{ platform_name }} registration",
        P.format("We could not approve the registration of <b>{{ company.name }}</b>.")
        + P.format("Reason: {{ reason }}")
        + P.format("Reply to this email or contact {{ support_email }} if you have questions."),
        ["platform_name", "company", "reason", "support_email"],
    ),
    (
        "team/invitation",
        "Team invitation",
        "{{ inviter.full_name|default:inviter.email }} invited you to {{ company.name }}",
        P.format("You have been invited to join <b>{{ company.name }}</b> on {{ platform_name }} as {{ role.name }}.")
        + P.format('<a href="{{ accept_url }}">Accept invitation</a>')
        + P.format("This invitation is valid until {{ expires_at|date:'d M Y' }}."),
        ["platform_name", "company", "inviter", "role", "accept_url", "expires_at"],
    ),
    (
        "website/enquiry_team",
        "Website enquiry (to platform team)",
        "New enquiry: {{ enquiry.business_name }}",
        P.format("A new enquiry arrived from the website.")
        + P.format("{{ enquiry.name }} — {{ enquiry.business_name }} ({{ enquiry.industry.name|default:'—' }})")
        + P.format("{{ enquiry.email }} · {{ enquiry.phone }}")
        + P.format("{{ enquiry.message|linebreaksbr }}")
        + P.format('<a href="{{ review_url }}">Open in Super Admin</a>'),
        ["platform_name", "enquiry", "review_url"],
    ),
    # Phase 3
    (
        "crm/task_reminder",
        "Follow-up task reminder",
        "Reminder: {{ task.title }}",
        P.format("Hello {{ user.full_name|default:user.email }},")
        + P.format("Your task <b>{{ task.title }}</b> is due at {{ task.due_at|date:'d M Y H:i' }}.")
        + P.format("{% if task.lead %}Lead: {{ task.lead }}{% endif %}")
        + P.format('<a href="{{ task_url }}">Open my follow-ups</a>'),
        ["platform_name", "task", "user", "task_url"],
    ),
]
