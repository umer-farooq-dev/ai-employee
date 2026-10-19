"""MOB-03 / CP-07: the company panel as an installable app — manifest, service worker (push alerts, offline page)."""

from django.http import JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import cache_control

from apps.platform_config import services as config


@cache_control(max_age=3600)
def manifest(request):
    """Name, colours and icon come from General Settings → Branding."""
    icons = [
        {"src": static("brand/app-icon-192.png"), "sizes": "192x192", "type": "image/png"},
        {"src": static("brand/app-icon-512.png"), "sizes": "512x512", "type": "image/png"},
        {"src": static("brand/app-icon-maskable.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
    ]
    if config.get("general.app_icon"):
        icons = [{"src": config.get("general.app_icon"), "sizes": "512x512", "purpose": "any"}, *icons]
    data = {
        "name": config.get("general.platform_name"),
        "short_name": config.get("general.short_name") or config.get("general.platform_name"),
        "description": config.get("general.tagline"),
        "start_url": "/app/",
        "scope": "/",
        "display": "standalone",
        "orientation": "portrait",
        "background_color": "#ffffff",
        "theme_color": config.get("general.color_company_panel"),
        "icons": icons,
    }
    return JsonResponse(data, content_type="application/manifest+json")


@cache_control(no_cache=True)
def service_worker(request):
    response = render(
        request,
        "panel/pwa/sw.js",
        {"icon": config.get("general.app_icon") or static("brand/app-icon-192.png")},
        content_type="application/javascript",
    )
    response["Service-Worker-Allowed"] = "/"
    return response


def offline(request):
    return render(request, "panel/pwa/offline.html")
