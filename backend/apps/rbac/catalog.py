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
    "industries.manage": (PLATFORM, "Manage industries and industry templates"),
    "crm_config.manage": (PLATFORM, "Configure CRM: statuses, sources, import limits"),
    "employee_roles.manage": (PLATFORM, "Manage AI Employee role templates"),
    "holidays.manage": (PLATFORM, "Manage platform holidays"),
    "ai_providers.manage": (PLATFORM, "Manage AI providers, keys and model per task"),
    "voice_settings.manage": (PLATFORM, "Manage speech / telephony providers, languages and voices"),
    "number_pool.manage": (PLATFORM, "Manage the phone-number pool and give numbers to companies"),
    "calls_oversight.view": (PLATFORM, "View calls of all companies with quality metrics"),
    "recordings_oversight.listen": (PLATFORM, "Listen to call recordings of any company (audited)"),
    "tools.manage": (PLATFORM, "Manage the AI tool registry"),
    "ai_oversight.view": (PLATFORM, "View AI Employees of all companies, conversations and tool logs"),
    "ai_oversight.manage": (PLATFORM, "Pause AI Employees, create the ready-made employee for a company"),
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
    "leads.view": (COMPANY, "View leads (assigned to me)"),
    "leads.view_all": (COMPANY, "View all leads of the company"),
    "leads.manage": (COMPANY, "Create and edit leads, notes and follow-ups"),
    "leads.assign": (COMPANY, "Assign leads and use bulk actions"),
    "leads.delete": (COMPANY, "Delete, restore and merge leads"),
    "leads.import": (COMPANY, "Import leads"),
    "leads.export": (COMPANY, "Export leads"),
    "crm.configure": (COMPANY, "Configure company CRM fields, scoring and assignment rules"),
    "catalog.view": (COMPANY, "View catalogue"),
    "catalog.manage": (COMPANY, "Manage catalogue items, collections and imports"),
    "calendar.view": (COMPANY, "View calendar"),
    "calendar.manage": (COMPANY, "Book and manage appointments"),
    "calendar.configure": (COMPANY, "Configure calendar resources and availability"),
    "ai_employees.view": (COMPANY, "View AI Employees"),
    "ai_employees.manage": (COMPANY, "Create, edit, test, activate and pause AI Employees"),
    "knowledge.view": (COMPANY, "View the knowledge base"),
    "knowledge.manage": (COMPANY, "Add, edit and delete knowledge sources and FAQs"),
    "knowledge.approve": (COMPANY, "Approve knowledge for the AI"),
    "conversations.view": (COMPANY, "View AI conversations, transcripts and tool logs"),
    "calls.view": (COMPANY, "View call logs, transcripts and call details"),
    "calls.make": (COMPANY, "Start outbound AI calls (Call now) and schedule follow-up calls"),
    "phone_numbers.manage": (COMPANY, "Connect phone numbers to AI Employees and set the company's calling rules"),
    "recordings.listen": (COMPANY, "Listen to call recordings"),
    "recordings.download": (COMPANY, "Download call recordings"),
    "handoffs.receive": (COMPANY, "Receive live calls and chats handed over by the AI"),
    "billing.view": (COMPANY, "View subscription and billing"),
    "billing.manage": (COMPANY, "Change subscription and billing"),
}

PLATFORM_KEYS = [k for k, (scope, _) in PERMISSIONS.items() if scope == PLATFORM]
COMPANY_KEYS = [k for k, (scope, _) in PERMISSIONS.items() if scope == COMPANY]

MANAGER_P3 = [
    "leads.view",
    "leads.view_all",
    "leads.manage",
    "leads.assign",
    "leads.import",
    "leads.export",
    "catalog.view",
    "catalog.manage",
    "calendar.view",
    "calendar.manage",
    "calendar.configure",
]
MANAGER_P4 = [
    "ai_employees.view",
    "ai_employees.manage",
    "knowledge.view",
    "knowledge.manage",
    "knowledge.approve",
    "conversations.view",
]
AGENT_P4 = ["ai_employees.view", "knowledge.view", "conversations.view"]
MANAGER_P5 = [
    "calls.view",
    "calls.make",
    "phone_numbers.manage",
    "recordings.listen",
    "recordings.download",
    "handoffs.receive",
]
AGENT_P5 = ["calls.view", "calls.make", "recordings.listen", "handoffs.receive"]
AGENT_P3 = ["leads.view", "leads.manage", "catalog.view", "calendar.view", "calendar.manage"]

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
    (COMPANY, "manager", "Manager", ["company.view", "team.view", *MANAGER_P3, *MANAGER_P4, *MANAGER_P5]),
    (COMPANY, "agent", "Human Agent", ["company.view", *AGENT_P3, *AGENT_P4, *AGENT_P5]),
]
