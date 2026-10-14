"""TEN-01/02/05/06 + AUTH-11: company isolation in ORM, API and PostgreSQL; suspension; RBAC; support login."""

import pytest
from django.db import connection

from apps.audit.models import AuditLog
from apps.rbac.catalog import PERMISSIONS, SEED_ROLES
from apps.rbac.models import Role
from apps.rbac.services import has_perm
from apps.tenancy import services as tenancy
from apps.tenancy.context import TenantContextMissing, company_context, platform_context
from apps.tenancy.models import Company, Membership


# ---------------------------------------------------------------- RBAC (AUTH-11, SEC-03)
@pytest.mark.django_db
def test_seeded_role_matrix():
    for scope, key, _, perms in SEED_ROLES:
        role = Role.objects.get(scope=scope, key=key)
        assert set(role.permissions) == set(perms)
        assert all(PERMISSIONS[p][0] == scope for p in role.permissions)


@pytest.mark.django_db
def test_rbac_matrix_for_staff_roles(client, super_admin, support):
    assert has_perm(super_admin, "plans.manage")
    assert has_perm(support, "companies.view") and not has_perm(support, "companies.manage")
    client.force_login(support)
    assert client.get("/superadmin/companies/").status_code == 200
    assert client.get("/superadmin/companies/new/").status_code == 403
    assert client.get("/superadmin/settings/general/").status_code == 403
    assert client.get("/api/v1/admin/plans/").status_code == 200  # plans.view
    new_plan = {"key": "gold", "name": "Gold"}
    assert client.post("/api/v1/admin/plans/", new_plan, content_type="application/json").status_code == 403
    support.platform_role.permissions.append("plans.manage")  # permissions are data, editable in Super Admin
    support.platform_role.save()
    assert client.post("/api/v1/admin/plans/", new_plan, content_type="application/json").status_code == 201


@pytest.mark.django_db
def test_company_permissions_follow_membership(owner_a, company_a, company_b):
    assert has_perm(owner_a, "team.manage", company_a)
    assert not has_perm(owner_a, "team.manage", company_b)
    assert not has_perm(owner_a, "companies.view")  # company users have no platform permissions


# ---------------------------------------------------------------- isolation (TEN-01, TEN-05)
@pytest.mark.django_db
def test_orm_is_scoped_and_fails_closed(owner_a, owner_b, company_a):
    with pytest.raises(TenantContextMissing):
        list(Membership.objects.all())
    with company_context(company_a.id):
        assert {m.user.email for m in Membership.objects.all()} == {owner_a.email}
    with platform_context():
        assert Membership.objects.count() == 2


@pytest.mark.django_db
def test_postgres_row_level_security_with_app_role(owner_a, owner_b, company_a):
    """SEC-05 + TEN-01: the least-privilege app role only sees the current company's rows, even with raw SQL."""
    from django.core.management import call_command

    call_command("setup_app_db_role", role="rls_probe")
    with connection.cursor() as cur:
        cur.execute("SET ROLE rls_probe")
        try:
            cur.execute(
                "SELECT set_config('app.company_id', %s, true), set_config('app.bypass_rls', '', true)",
                [str(company_a.id)],
            )
            cur.execute("SELECT count(*) FROM tenancy_membership")
            assert cur.fetchone()[0] == 1  # only company A's row
            cur.execute("SELECT set_config('app.company_id', '', true)")
            cur.execute("SELECT count(*) FROM tenancy_membership")
            assert cur.fetchone()[0] == 0  # no company context = no rows
            cur.execute("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = 'rls_probe'")
            assert cur.fetchone()[0] is False
        finally:
            cur.execute("RESET ROLE")


@pytest.mark.django_db
def test_api_isolation_between_companies(client, owner_a, owner_b, company_a):
    client.force_login(owner_a)
    assert client.get("/api/v1/company/").json()["id"] == str(company_a.id)
    for path in (
        "/api/v1/admin/companies/",
        "/api/v1/admin/users/",
        "/api/v1/admin/logs/audit/",
        "/api/v1/admin/settings/general/",
        "/api/v1/admin/cms/pages/",
        "/api/v1/admin/roles/",
    ):
        assert client.get(path).status_code == 403, path


# ---------------------------------------------------------------- suspension (TEN-06)
@pytest.mark.django_db
def test_suspended_company_users_are_signed_out(client, owner_a, company_a):
    client.force_login(owner_a)
    tenancy.set_status(company_a, Company.SUSPENDED, "unpaid")
    response = client.get("/app/")
    assert response.status_code == 302 and "/accounts/login/" in response.url
    assert client.get("/api/v1/me/").status_code in (401, 403)
    assert AuditLog.objects.filter(action="company.suspended", category="security").exists()


@pytest.mark.django_db
def test_suspend_and_reactivate_from_super_admin(admin_client, company_a):
    admin_client.post(f"/superadmin/companies/{company_a.pk}/status/", {"status": "suspended", "reason": "fraud"})
    company_a.refresh_from_db()
    assert company_a.status == "suspended" and company_a.suspended_reason == "fraud"
    admin_client.post(f"/superadmin/companies/{company_a.pk}/status/", {"status": "active"})
    company_a.refresh_from_db()
    assert company_a.status == "active"


# ---------------------------------------------------------------- support login (SA-03)
@pytest.mark.django_db
def test_impersonation_is_audited_and_reversible(admin_client, super_admin, owner_a, company_a):
    response = admin_client.post(
        f"/superadmin/companies/{company_a.pk}/impersonate/", {"user": owner_a.pk, "reason": "Customer asked for help"}
    )
    assert response.url == "/app/"
    page = admin_client.get("/app/").content.decode()
    assert "Support login" in page and owner_a.email in page
    entry = AuditLog.objects.get(action="support.impersonate_start")
    assert entry.changes["reason"] == "Customer asked for help"
    admin_client.post("/support/stop/")
    assert admin_client.get("/superadmin/").status_code == 200


@pytest.mark.django_db
def test_staff_cannot_be_impersonated(admin_client, support, company_a):
    tenancy.add_member(company_a, support.email, Role.objects.get(scope="company", key="agent"))
    admin_client.post(f"/superadmin/companies/{company_a.pk}/impersonate/", {"user": support.pk, "reason": "x"})
    assert not AuditLog.objects.filter(action="support.impersonate_start").exists()
