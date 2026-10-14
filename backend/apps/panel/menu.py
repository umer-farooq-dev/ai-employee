"""Company panel navigation (CP-02). Items show per role (permission) and plan (entitlement with limit 0 = hidden).

`url` is set when the screen exists; until its phase, an item opens the "coming soon" page so the shell is complete.
"""

from apps.rbac.services import has_perm

# key, label, icon, url name (None = later phase), permission, plan entitlement, phase
MENU = [
    ("dashboard", "Dashboard", "home-simple", "panel:company_home", "company.view", None, 2),
    ("ai_employees", "AI Employees", "user-star", None, "company.view", "ai_employees", 4),
    ("leads", "Leads", "group", None, "company.view", None, 3),
    ("calendar", "Calendar", "calendar", None, "company.view", None, 3),
    ("conversations", "Conversations", "chat-lines", None, "company.view", None, 5),
    ("campaigns", "Campaigns", "megaphone", None, "company.view", "campaigns", 6),
    ("knowledge", "Knowledge Base", "book-stack", None, "company.view", None, 4),
    ("catalogue", "Catalogue", "package", None, "company.view", None, 3),
    ("analytics", "Analytics", "stats-up-square", None, "company.view", None, 7),
    ("billing", "Billing & Usage", "wallet", None, "billing.view", None, 7),
    ("team", "Team", "group", "panel:team", "team.view", None, 2),
    ("settings", "Settings", "settings", "panel:company_settings", "company.view", None, 2),
    ("support", "Support", "headset-help", None, "company.view", None, 7),
]
BY_KEY = {row[0]: row for row in MENU}


def _plan_allows(company, entitlement):
    if not entitlement or not company.plan_id:
        return True
    row = company.plan.entitlements.filter(key=entitlement).first()
    return row is None or row.limit_value is None or row.limit_value > 0


def items(user, company):
    from django.urls import reverse

    out = []
    for key, label, icon, url_name, perm, entitlement, phase in MENU:
        if company and has_perm(user, perm, company) and _plan_allows(company, entitlement):
            url = reverse(url_name) if url_name else reverse("panel:coming_soon", args=[key])
            out.append({"key": key, "label": label, "icon": icon, "url": url, "ready": bool(url_name), "phase": phase})
    return out
