"""Catalogue of permission keys (what the code can check) and the SEED role matrix (PRD-01 Section 5).

Which role has which permission is data (Role.permissions) edited in Super Admin. Later phases add their own keys and
extend the seed roles with a data migration.
"""

PLATFORM = "platform"
COMPANY = "company"

PERMISSIONS = {
    # platform (Super Admin)
    "dashboard.view": (PLATFORM, "View Super Admin dashboard"),
    "companies.view": (PLATFORM, "View companies"),
    "companies.manage": (PLATFORM, "Create and edit companies, change plan"),
    "companies.suspend": (PLATFORM, "Suspend / reactivate companies"),
    "companies.impersonate": (PLATFORM, "Support login (impersonate a company user)"),
    "companies.export": (PLATFORM, "Export company data"),
    "companies.delete": (PLATFORM, "Delete companies"),
    "companies.approve": (PLATFORM, "Approve / reject new company registrations"),
    "industries.manage": (PLATFORM, "Manage industries"),
    "enquiries.view": (PLATFORM, "View website enquiries"),
    "enquiries.manage": (PLATFORM, "Update website enquiries"),
    "users.view": (PLATFORM, "View users"),
    "users.manage": (PLATFORM, "Create and edit users and staff"),
    "users.security": (PLATFORM, "Lock / unlock, reset password, reset 2FA, end sessions"),
    "roles.manage": (PLATFORM, "Manage roles and permissions"),
    "plans.view": (PLATFORM, "View plans"),
    "plans.manage": (PLATFORM, "Manage plans, prices and limits"),
    "settings.general": (PLATFORM, "Edit General Settings"),
    "settings.system": (PLATFORM, "Edit system settings (registration, security)"),
    "cms.view": (PLATFORM, "View website content"),
    "cms.manage": (PLATFORM, "Edit and publish website content"),
    "email_templates.manage": (PLATFORM, "Edit email templates"),
    "logs.view": (PLATFORM, "View audit, API and error logs"),
    "security.manage": (PLATFORM, "View security events and sessions"),
    # company (company panel; grows phase by phase)
    "company.view": (COMPANY, "View company profile"),
    "company.manage": (COMPANY, "Edit company profile and settings"),
    "team.view": (COMPANY, "View team members"),
    "team.manage": (COMPANY, "Invite and manage team members"),
    "billing.view": (COMPANY, "View subscription and billing"),
    "billing.manage": (COMPANY, "Change subscription and billing"),
}

PLATFORM_KEYS = [k for k, (scope, _) in PERMISSIONS.items() if scope == PLATFORM]
COMPANY_KEYS = [k for k, (scope, _) in PERMISSIONS.items() if scope == COMPANY]

SEED_ROLES = [
    # (scope, key, name, permissions)
    (PLATFORM, "super_admin", "Super Admin", PLATFORM_KEYS),
    (
        PLATFORM,
        "support",
        "Support",
        [
            "dashboard.view",
            "companies.view",
            "companies.impersonate",
            "users.view",
            "plans.view",
            "cms.view",
            "logs.view",
            "enquiries.view",
            "enquiries.manage",
        ],
    ),
    (COMPANY, "owner", "Owner / Admin", COMPANY_KEYS),
    (COMPANY, "manager", "Manager", ["company.view", "team.view"]),
    (COMPANY, "agent", "Human Agent", ["company.view"]),
]
