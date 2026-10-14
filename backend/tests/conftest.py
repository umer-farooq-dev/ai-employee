import pytest
from allauth.account.models import EmailAddress
from allauth.mfa.models import Authenticator
from django.core.cache import cache

from apps.accounts.models import User
from apps.platform_config.models import PlatformSetting
from apps.platform_config.services import CACHE_KEY
from apps.rbac.models import Role
from apps.tenancy.models import Company
from apps.tenancy.services import add_member

PASSWORD = "a-strong-password-123"


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def set_setting(db):
    def _set(key, value):
        PlatformSetting.objects.update_or_create(key=key, defaults={"value": value})
        cache.delete(CACHE_KEY)

    return _set


def make_user(email, staff_role=None, with_2fa=False, password=PASSWORD):
    user = User.objects.create_user(
        email,
        password,
        is_staff=bool(staff_role),
        platform_role=Role.objects.get(scope="platform", key=staff_role) if staff_role else None,
    )
    EmailAddress.objects.create(user=user, email=email, primary=True, verified=True)
    if with_2fa:
        Authenticator.objects.create(user=user, type=Authenticator.Type.TOTP, data={"secret": "x"})
    return user


@pytest.fixture
def super_admin(db):
    return make_user("admin@example.com", "super_admin", with_2fa=True)


@pytest.fixture
def support(db):
    return make_user("support@example.com", "support", with_2fa=True)


@pytest.fixture
def company_a(db):
    return Company.objects.create(name="Alpha Realty", slug="alpha")


@pytest.fixture
def company_b(db):
    return Company.objects.create(name="Beta Travels", slug="beta")


@pytest.fixture
def owner_a(company_a):
    user = make_user("owner@alpha.example")
    add_member(company_a, user.email, Role.objects.get(scope="company", key="owner"))
    return user


@pytest.fixture
def owner_b(company_b):
    user = make_user("owner@beta.example")
    add_member(company_b, user.email, Role.objects.get(scope="company", key="owner"))
    return user


@pytest.fixture
def admin_client(client, super_admin):
    client.force_login(super_admin)
    return client
