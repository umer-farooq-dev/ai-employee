"""Public website: what a page shows (WEB-01..03) and contact / demo enquiries (WEB-06)."""

import json

from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.audit.services import record
from apps.billing.models import Plan
from apps.cms import services as cms
from apps.cms.models import Page
from apps.core.india import normalise_phone
from apps.core.request import client_ip
from apps.industries.models import Industry
from apps.notifications import services as mail

from .models import Enquiry

SITE_PAGE = "_site"


def site_sections() -> dict:
    """Header, call to action and footer content from the site-wide page (only visible, published sections)."""
    _, sections = cms.published_page(SITE_PAGE)
    return {s["type"]: s["content"] for s in sections}


def public_plans():
    return Plan.objects.filter(is_public=True, status=Plan.ACTIVE)


def active_industries():
    return Industry.objects.filter(is_active=True)


def structured_data(request) -> str:
    """WEB-07: schema.org Organization from General Settings, safe to place inside a <script> tag."""
    from apps.platform_config import services as config

    root = request.build_absolute_uri("/")
    logo = config.get("general.logo_dark")
    data = {
        "@context": "https://schema.org",
        "@type": "Organization",
        "name": config.get("general.platform_name"),
        "url": root,
        "logo": logo if logo.startswith("http") else root.rstrip("/") + logo,
        "sameAs": [link["url"] for link in config.get("contact.social_links")],
    }
    if config.get("contact.support_phone") or config.get("contact.support_email"):
        data["contactPoint"] = {
            "@type": "ContactPoint",
            "contactType": "customer support",
            "telephone": config.get("contact.support_phone"),
            "email": config.get("contact.support_email"),
        }
    return json.dumps(data).replace("<", "\\u003c")


def page_context(slug: str) -> dict:
    page = Page.objects.exclude(slug=SITE_PAGE).get(slug=slug)
    _, sections = cms.published_page(slug)
    return {"page": page, "sections": sections}


def create_enquiry(data: dict, request=None) -> Enquiry:
    from apps.accounts.models import phone_validator

    phone = normalise_phone(data.get("phone", ""))
    phone_validator(phone)
    enquiry = Enquiry.objects.create(
        name=data["name"],
        business_name=data["business_name"],
        phone=phone,
        email=data["email"],
        industry=data.get("industry"),
        message=data.get("message", ""),
        source_url=(request.META.get("HTTP_REFERER", "") if request else "")[:500],
        ip=client_ip(request) if request else None,
    )
    record(request, "enquiry.create", "enquiry", enquiry.id, changes={"email": enquiry.email})
    review_url = reverse("superadmin:enquiry_detail", args=[enquiry.pk])
    context = {"enquiry": enquiry, "review_url": request.build_absolute_uri(review_url) if request else review_url}
    for to in mail.team_recipients():
        mail.send("website/enquiry_team", to, context)
    return enquiry


def update_enquiry(enquiry: Enquiry, status: str, notes: str, user=None, request=None) -> Enquiry:
    if status not in dict(Enquiry.STATUSES):
        raise ValidationError("Invalid status.")
    enquiry.status, enquiry.notes, enquiry.handled_by = status, notes, user
    enquiry.save(update_fields=["status", "notes", "handled_by", "updated_at"])
    record(request, "enquiry.update", "enquiry", enquiry.id, changes={"status": status})
    return enquiry
