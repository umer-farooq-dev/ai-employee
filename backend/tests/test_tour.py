"""Guided panel tour: opens on a person's first dashboard visit, not again once finished or skipped, and on demand."""

import pytest

from apps.tenancy.models import Membership


@pytest.mark.django_db
def test_tour_opens_once_and_on_demand(client, company_a, owner_a):
    company_a.status = company_a.ACTIVE
    company_a.save()
    client.force_login(owner_a)
    first = client.get("/app/").content.decode()
    assert "driver.js" in first and 'data-tour="ai_employees"' in first and 'var company = "Alpha Realty"' in first
    assert client.post("/app/tour/done/").status_code == 204
    assert Membership.all_companies.get(company=company_a, user=owner_a).tour_done_at
    assert "driver.js" not in client.get("/app/").content.decode()
    assert "driver.js" in client.get("/app/?tour=1").content.decode()  # the "?" button in the top bar
