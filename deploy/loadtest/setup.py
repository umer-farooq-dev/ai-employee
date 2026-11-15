# ENGR-07: test companies for the API load test. Staging / CI only (seed_demo refuses production).
#   docker compose -f deploy/docker-compose.prod.yml exec -T -e LOADTEST_PASSWORD=... web \
#       python manage.py shell -c "import sys; exec(sys.stdin.read())" < deploy/loadtest/setup.py
# Creates LOADTEST_COMPANIES companies (owner loadtest-<n>@example.com, demo leads / calendar / catalogue) and lifts the
# API rate limits of this environment, so the test measures capacity rather than the limiter. Restore the limits in
# Super Admin → System Settings → Security after a staging run.
import os

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.platform_config import services as config
from apps.rbac.models import Role
from apps.tenancy.context import platform_context
from apps.tenancy.models import Company
from apps.tenancy.services import add_member, create_company

password = os.environ["LOADTEST_PASSWORD"]
count = int(os.environ.get("LOADTEST_COMPANIES", "10"))
owner = Role.objects.get(scope="company", key="owner")
config.update({"security.api_rate_user": "100000/hour", "security.api_rate_company": "100000/hour"})
with platform_context():
    for n in range(1, count + 1):
        email = f"loadtest-{n}@example.com"
        user = get_user_model().objects.filter(email=email).first()
        if not user:
            user = get_user_model().objects.create_user(email, password)
            EmailAddress.objects.create(user=user, email=email, primary=True, verified=True)
        company = Company.objects.filter(name=f"Load test {n}").first() or create_company(
            {"name": f"Load test {n}", "status": Company.ACTIVE, "state": "Maharashtra"}
        )
        add_member(company, email, owner)
        call_command("seed_demo", "--company", company.name)
print(f"load test: {count} companies ready")
