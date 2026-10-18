"""Public website (WEB-01..08): every page and section is read from the Super Admin CMS."""

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.cms.models import Page
from apps.core import ratelimit
from apps.core.request import client_ip
from apps.industries.models import Industry
from apps.platform_config import services as config

from . import services
from .forms import EnquiryForm


def _render(request, template, context, status=200):
    context = {
        "site": services.site_sections(),
        "plans": services.public_plans(),
        "industries": services.active_industries(),
        "enquiry_form": EnquiryForm(),
        "structured_data": services.structured_data(request),
        **context,
    }
    return render(request, template, context, status=status)


def page(request, slug=""):
    try:
        context = services.page_context(slug)
    except Page.DoesNotExist:
        raise Http404 from None
    return _render(request, "website/page.html", context)


NOT_FOUND_PAGE = "not-found"


def not_found(request, exception=None):
    """handler404: the "Page not found" CMS page (Super Admin → Website), with the site header and footer."""
    if request.path.startswith(("/api/", "/public/")):
        from django.http import JsonResponse

        return JsonResponse({"error": {"code": "not_found", "message": "Not found."}}, status=404)
    try:
        context = services.page_context(NOT_FOUND_PAGE)
    except Page.DoesNotExist:
        return HttpResponse("Page not found", status=404, content_type="text/plain")
    return _render(request, "website/page.html", context, status=404)


def server_error(request):
    """handler500: a self-contained page — the database may be the thing that failed."""
    return render(request, "website/500.html", status=500)


def industry(request, key):
    item = get_object_or_404(Industry, key=key, is_active=True)
    return _render(request, "website/industry.html", {"industry": item})


@require_POST
def enquiry(request):
    """WEB-06: contact / demo form → Super Admin → Enquiries + email to the platform team."""
    back = request.POST.get("next") or reverse("website:page", args=["contact"])
    if not back.startswith("/") or back.startswith("//"):
        back = "/"
    form = EnquiryForm(request.POST)
    if not ratelimit.allow("enquiry", client_ip(request) or "-", config.get("security.api_rate_public_form")):
        messages.error(request, "Too many messages from your network. Please try again later.")
    elif form.is_valid():
        if not form.is_spam:
            services.create_enquiry(form.cleaned_data, request=request)
        return redirect(f"{back}?sent=1#contact")  # the section shows its CMS "message after sending"
    else:
        for field, errors in form.errors.items():
            label = form.fields[field].label if field in form.fields else ""
            messages.error(request, f"{label}: {errors[0]}" if label else errors[0])
    return redirect(f"{back}#contact")


def robots(request):
    if not config.get("seo.allow_indexing"):
        return HttpResponse("User-agent: *\nDisallow: /\n", content_type="text/plain")
    lines = ["User-agent: *"] + [f"Disallow: {p}" for p in ("/superadmin/", "/app/", "/api/", "/accounts/")]
    lines.append(f"Sitemap: {request.build_absolute_uri(reverse('website:sitemap'))}")
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain")


def sitemap(request):
    urls = [
        request.build_absolute_uri(reverse("website:page", args=[p.slug]) if p.slug else "/")
        for p in Page.objects.exclude(slug__in=[services.SITE_PAGE, NOT_FOUND_PAGE])
    ] + [request.build_absolute_uri(reverse("website:industry", args=[i.key])) for i in services.active_industries()]
    return render(request, "website/sitemap.xml", {"urls": urls}, content_type="application/xml")
