import pytest
from django.core.management import call_command

from apps.catalog.models import CatalogItem
from apps.crm.models import Lead
from apps.industries.models import Industry
from apps.tenancy.models import Company


@pytest.mark.django_db
def test_seed_demo_fills_a_company_once(company_a):
    industry = Industry.objects.get(key="real-estate")
    company_a.industry, company_a.template_version = industry, industry.published_version
    company_a.save()
    call_command("seed_demo", company=company_a.name)
    leads = Lead.all_companies.filter(company=company_a, tags__contains=["demo"])
    assert leads.count() == 24 and CatalogItem.all_companies.filter(company=company_a).count() == 8
    assert Company.objects.filter(name="Sunrise Travels (demo)", status=Company.PENDING).exists()
    call_command("seed_demo", company=company_a.name)  # second run changes nothing
    assert leads.count() == 24
