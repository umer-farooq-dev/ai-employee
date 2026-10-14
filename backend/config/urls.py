from django.conf import settings
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.api.urls import api_v1, public_v1

urlpatterns = [
    path("", include("apps.website.urls")),
    path("", include("apps.panel.urls")),
    path("", include("apps.core.urls")),
    path("superadmin/", include("apps.superadmin.urls")),
    path("accounts/", include("allauth.urls")),
    # Login / 2FA / password API for browser and app clients (API-02: Bearer JWT for the app)
    path("api/v1/auth/", include("allauth.headless.urls")),
    path("api/v1/", include((api_v1, "api"), namespace="api")),
    path("public/v1/", include((public_v1, "public"), namespace="public")),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/v1/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="api-docs"),
]

if settings.DEBUG:
    from django.conf.urls.static import static

    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
