"""Settings registry (docs/phase0/settings-registry.md).

Only keys, types and SEED defaults live here. Live values are stored in the database (PlatformSetting) and edited in
Super Admin; code always reads them through apps.platform_config.services.get(). Later phases add their own groups.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Setting:
    key: str
    type: str  # text | textarea | rich | image | color | email | phone | url | number | boolean | choice | list | links
    default: object
    label: str
    group: str
    help: str = ""
    choices: tuple = field(default_factory=tuple)
    min: int | None = None
    max: int | None = None


GROUPS = {
    # group key: (screen, title)
    "branding": ("general", "Branding"),
    "contact": ("general", "Contact & company details"),
    "locale": ("general", "Localisation"),
    "seo_email": ("general", "SEO & email"),
    "maintenance": ("general", "Maintenance mode"),
    "registration": ("system", "Registration & team"),
    "security": ("system", "Security"),
    "sms": ("system", "SMS (mobile OTP)"),
}

TIMEZONES = (("Asia/Kolkata", "Asia/Kolkata (IST)"), ("UTC", "UTC"))
LANGUAGES = (("en", "English"), ("hi", "Hindi"), ("bn", "Bengali"))

SETTINGS = [
    # A. General Settings (SA-21 … SA-27)
    Setting("general.platform_name", "text", "AI Employee", "Platform name", "branding"),
    Setting("general.short_name", "text", "AIE", "Short name", "branding"),
    Setting("general.tagline", "text", "Hire an AI Employee for your business", "Tagline", "branding"),
    Setting(
        "general.logo_light", "image", "/static/panel/images/logo-light.png", "Logo (for dark backgrounds)", "branding"
    ),
    Setting(
        "general.logo_dark",
        "image",
        "/static/website/img/logo/header-logo2.png",
        "Logo (for light backgrounds)",
        "branding",
    ),
    Setting("general.logo_small", "image", "/static/panel/images/logo-sm.png", "Small logo / icon", "branding"),
    Setting("general.favicon", "image", "/static/panel/images/favicon.ico", "Favicon", "branding"),
    Setting("general.app_icon", "image", "", "App / PWA icon", "branding"),
    Setting("general.login_image", "image", "", "Login page image", "branding"),
    Setting("general.color_primary", "color", "#6534F4", "Primary colour", "branding"),
    Setting("general.color_secondary", "color", "#101537", "Secondary colour", "branding"),
    Setting("general.color_company_panel", "color", "#0D9488", "Company panel accent colour", "branding"),
    Setting("general.widget_powered_by", "text", "Powered by AI Employee", 'Chat widget "Powered by" text', "branding"),
    Setting("contact.support_email", "email", "", "Support email", "contact"),
    Setting(
        "contact.support_phone",
        "phone",
        "",
        "Support phone",
        "contact",
        help="International format, e.g. +919876543210",
    ),
    Setting("contact.whatsapp", "phone", "", "WhatsApp number", "contact"),
    Setting("contact.address", "textarea", "", "Office address", "contact"),
    Setting("contact.legal_name", "text", "", "Legal company name", "contact"),
    Setting("contact.gstin", "text", "", "GSTIN", "contact"),
    Setting("contact.pan", "text", "", "PAN", "contact"),
    Setting("contact.social_links", "links", [], "Social media links", "contact"),
    Setting(
        "contact.team_notify_emails",
        "list",
        [],
        "Team notification emails",
        "contact",
        help="New registrations and website enquiries are emailed here. Empty = support email.",
    ),
    Setting(
        "contact.copyright",
        "text",
        "© {year} AI Employee",
        "Copyright text",
        "contact",
        help="{year} is replaced with the current year",
    ),
    Setting("locale.timezone", "choice", "Asia/Kolkata", "Timezone", "locale", choices=TIMEZONES),
    Setting("locale.currency", "choice", "INR", "Currency", "locale", choices=(("INR", "Indian Rupee (₹)"),)),
    Setting(
        "locale.number_format",
        "choice",
        "indian",
        "Number format",
        "locale",
        choices=(("indian", "Indian (12,34,567 · lakh / crore)"), ("international", "International (1,234,567)")),
    ),
    Setting("locale.default_language", "choice", "en", "Default language", "locale", choices=LANGUAGES),
    Setting("seo.meta_title", "text", "", "Default meta title", "seo_email"),
    Setting("seo.meta_description", "textarea", "", "Default meta description", "seo_email"),
    Setting("seo.og_image", "image", "", "Default social share image", "seo_email"),
    Setting("seo.analytics_ids", "list", [], "Analytics tracking IDs", "seo_email", help="Google tag IDs, e.g. G-XXXX"),
    Setting(
        "seo.allow_indexing",
        "boolean",
        True,
        "Allow search engines",
        "seo_email",
        help="Switch off on demo / staging servers so they are not listed in Google.",
    ),
    Setting("email.sender_name", "text", "AI Employee", "Email sender name", "seo_email"),
    Setting("email.sender_address", "email", "no-reply@localhost", "Email sender address", "seo_email"),
    Setting("email.header_html", "rich", "", "Email header", "seo_email"),
    Setting("email.footer_html", "rich", "", "Email footer", "seo_email"),
    Setting(
        "maintenance.enabled",
        "boolean",
        False,
        "Maintenance mode on",
        "maintenance",
        help="Website and panels show the maintenance page; Super Admin stays available.",
    ),
    Setting(
        "maintenance.message",
        "rich",
        "We are upgrading the platform. Please check back shortly.",
        "Maintenance message",
        "maintenance",
    ),
    # B. Registration (used by company registration in Phase 2)
    Setting("registration.enabled", "boolean", True, "Company registration open", "registration"),
    Setting(
        "registration.approval_required",
        "boolean",
        True,
        "New companies need Super Admin approval",
        "registration",
        help="While pending, the owner can sign in but only sees the approval status page.",
    ),
    Setting(
        "registration.email_verification",
        "choice",
        "optional",
        "Email verification",
        "registration",
        choices=(("mandatory", "Mandatory"), ("optional", "Optional")),
        help="Optional during development; set to Mandatory before launch.",
    ),
    Setting("registration.mobile_otp_required", "boolean", False, "Mobile OTP verification", "registration"),
    Setting("registration.otp_length", "number", 6, "OTP length (digits)", "registration", min=4, max=8),
    Setting("registration.otp_valid_minutes", "number", 10, "OTP valid for (minutes)", "registration", min=1, max=60),
    Setting("registration.otp_max_attempts", "number", 5, "Wrong OTP attempts allowed", "registration", min=1, max=20),
    Setting("registration.trial_enabled", "boolean", True, "Free trial", "registration"),
    Setting("registration.trial_days", "number", 14, "Trial days", "registration", min=0, max=365),
    Setting("registration.default_plan", "text", "starter", "Default plan key", "registration"),
    Setting(
        "registration.business_sizes",
        "list",
        ["1-10", "11-50", "51-200", "201+"],
        "Business size options",
        "registration",
        help="One option per line (employees).",
    ),
    Setting("team.invite_valid_days", "number", 7, "Team invitation valid for (days)", "registration", min=1, max=90),
    # C. Security
    Setting("security.password_min_length", "number", 10, "Minimum password length", "security", min=8, max=128),
    Setting("security.lockout_attempts", "number", 5, "Failed logins before lockout", "security", min=3, max=50),
    Setting("security.lockout_minutes", "number", 15, "Lockout duration (minutes)", "security", min=1, max=1440),
    Setting(
        "security.session_timeout_minutes",
        "number",
        120,
        "Session timeout (minutes of inactivity)",
        "security",
        min=5,
        max=43200,
    ),
    Setting("security.staff_2fa_required", "boolean", False, "2FA mandatory for platform staff", "security"),
    Setting(
        "security.company_2fa_enforced",
        "boolean",
        False,
        "Enforce 2FA for all company users",
        "security",
        help="Companies can also enable it for themselves.",
    ),
    Setting(
        "security.admin_ip_allowlist",
        "list",
        [],
        "Super Admin IP allowlist (IPs or CIDR ranges)",
        "security",
        help="Empty list = no IP restriction.",
    ),
    Setting("security.upload_max_mb", "number", 25, "Maximum upload size (MB)", "security", min=1, max=500),
    Setting(
        "security.upload_allowed_types",
        "list",
        ["pdf", "docx", "xlsx", "csv", "png", "jpg", "jpeg", "webp", "svg", "ico"],
        "Allowed upload file types",
        "security",
    ),
    Setting(
        "security.signed_url_seconds",
        "number",
        300,
        "Private file link validity (seconds)",
        "security",
        min=30,
        max=86400,
    ),
    Setting(
        "security.api_rate_user",
        "text",
        "1000/hour",
        "API rate limit per user",
        "security",
        help="Format: number/second|minute|hour|day",
    ),
    Setting("security.api_rate_anon", "text", "100/hour", "API rate limit per IP (anonymous)", "security"),
    Setting("security.api_rate_company", "text", "5000/hour", "API rate limit per company", "security"),
    Setting(
        "security.api_rate_public_form", "text", "10/hour", "Website forms per IP (registration, enquiries)", "security"
    ),
    # SMS for mobile OTP (AUTH-02). Real providers are added with their credentials when the client chooses one.
    Setting(
        "sms.provider",
        "choice",
        "log",
        "SMS provider",
        "sms",
        choices=(("log", "Development log (no SMS is sent)"),),
        help="The development log only works on local / test servers.",
    ),
    Setting(
        "sms.otp_message",
        "text",
        "{{ code }} is your {{ platform_name }} verification code. It expires in {{ minutes }} minutes.",
        "OTP message",
        "sms",
        help="Variables: {{ code }}, {{ minutes }}, {{ platform_name }}",
    ),
]

BY_KEY = {s.key: s for s in SETTINGS}
