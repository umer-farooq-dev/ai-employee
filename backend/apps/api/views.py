"""REST API v1 (API-01): every Phase 1 feature, used by the panels and, later, the Flutter app."""

from allauth.usersessions.models import UserSession
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import services as user_services
from apps.audit.models import ApiRequestLog, AuditLog, ErrorLog
from apps.audit.services import record
from apps.billing.models import Plan
from apps.cms import services as cms
from apps.cms.models import Page, Section
from apps.core.uploads import save_public
from apps.industries.models import Industry
from apps.notifications.models import EmailTemplate
from apps.platform_config import services as config
from apps.platform_config.registry import GROUPS, SETTINGS
from apps.rbac.models import Role
from apps.tenancy import services as tenancy
from apps.tenancy.models import Company
from apps.website import services as website
from apps.website.models import Enquiry

from . import serializers as s
from .base import AdminViewSet, TenantContextMixin, any_perm, perm
from .pagination import UserPagination


def _django_errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DjangoValidationError as exc:
        raise ValidationError(exc.messages) from None


# ------------------------------------------------------------------ me / own company
class MeView(TenantContextMixin, generics.RetrieveUpdateAPIView):
    """AUTH-08: the signed-in user's profile."""

    serializer_class = s.MeSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_object(self):
        return self.request.user

    def perform_update(self, serializer):
        serializer.save()
        record(self.request, "profile.update", "user", self.request.user.id)


# ------------------------------------------------------------------ admin: companies & users
class CompanyViewSet(AdminViewSet):
    serializer_class = s.CompanySerializer
    view_perm, manage_perm = "companies.view", "companies.manage"
    filterset_fields = ["status"]

    def get_queryset(self):
        qs = Company.objects.filter(deleted_at__isnull=True).select_related("plan")
        q = self.request.query_params.get("search")
        if q:
            qs = qs.filter(Q(name__icontains=q) | Q(email__icontains=q) | Q(slug__icontains=q))
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        owner = self.request.data.get("owner_email")
        serializer.instance = tenancy.create_company(data, owner_email=owner, request=self.request)

    def perform_update(self, serializer):
        company = serializer.save()
        record(self.request, "company.update", "company", company.id, company=company, changes=serializer.data)

    def destroy(self, request, *args, **kwargs):
        if not perm("companies.delete")().has_permission(request, self):
            return Response(status=status.HTTP_403_FORBIDDEN)
        tenancy.soft_delete(self.get_object(), request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated, perm("companies.suspend")])
    def suspend(self, request, pk=None):
        tenancy.set_status(self.get_object(), Company.SUSPENDED, request.data.get("reason", ""), request=request)
        return Response(s.CompanySerializer(self.get_object()).data)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated, perm("companies.suspend")])
    def activate(self, request, pk=None):
        tenancy.set_status(self.get_object(), Company.ACTIVE, request=request)
        return Response(s.CompanySerializer(self.get_object()).data)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated, perm("companies.approve")])
    def approve(self, request, pk=None):
        """AUTH-12: approve a pending (or rejected) registration; the owner is emailed."""
        company = _django_errors(tenancy.approve_company, self.get_object(), request=request._request)
        return Response(s.CompanySerializer(company).data)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated, perm("companies.approve")])
    def reject(self, request, pk=None):
        company = _django_errors(
            tenancy.reject_company, self.get_object(), request.data.get("reason", ""), request=request._request
        )
        return Response(s.CompanySerializer(company).data)

    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated, perm("companies.manage")])
    def template(self, request, pk=None):
        """IND-03: move the company to another published / archived version of its industry (upgrade or rollback)."""
        from apps.industries import services as templates
        from apps.industries.models import TemplateVersion

        company = self.get_object()
        version = get_object_or_404(TemplateVersion, pk=request.data.get("version"))
        _django_errors(templates.assign_version, company, version, request=request._request)
        return Response(s.CompanySerializer(company).data)

    @action(detail=True, methods=["get"], permission_classes=[permissions.IsAuthenticated, perm("companies.export")])
    def export(self, request, pk=None):
        return Response(tenancy.export_company(self.get_object(), request=request), content_type="application/json")


class IndustryViewSet(AdminViewSet):
    """Industries shown on the website and in registration (templates are added in Phase 3)."""

    serializer_class = s.IndustrySerializer
    view_perm = manage_perm = "industries.manage"
    pagination_class = None
    http_method_names = ["get", "post", "patch", "head", "options"]
    queryset = Industry.objects.all()

    def perform_create(self, serializer):
        item = serializer.save()
        record(self.request, "industry.save", "industry", item.id, changes=serializer.data)

    perform_update = perform_create


class EnquiryViewSet(AdminViewSet):
    """WEB-06 inbox: list / filter by status, update status and notes."""

    serializer_class = s.EnquirySerializer
    view_perm, manage_perm = "enquiries.view", "enquiries.manage"
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        qs = Enquiry.objects.select_related("industry")
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs

    def perform_update(self, serializer):
        d = serializer.validated_data
        e = serializer.instance
        serializer.instance = _django_errors(
            website.update_enquiry,
            e,
            d.get("status", e.status),
            d.get("notes", e.notes),
            self.request.user,
            self.request._request,
        )


class UserViewSet(AdminViewSet):
    serializer_class = s.UserSerializer
    pagination_class = UserPagination
    view_perm, manage_perm = "users.view", "users.manage"
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        qs = s.User.objects.select_related("platform_role").order_by("-date_joined")
        q = self.request.query_params.get("search")
        if q:
            qs = qs.filter(Q(email__icontains=q) | Q(full_name__icontains=q))
        if self.request.query_params.get("staff") in ("1", "true"):
            qs = qs.filter(is_staff=True)
        return qs

    def perform_create(self, serializer):
        d = serializer.validated_data
        serializer.instance = _django_errors(
            user_services.create_user,
            d["email"],
            d.get("full_name", ""),
            d.get("phone", ""),
            is_staff=d.get("is_staff", False),
            platform_role=d.get("platform_role"),
            request=self.request,
        )

    def perform_update(self, serializer):
        user = serializer.save()
        record(self.request, "user.update", "user", user.id, changes=serializer.data, category="security")

    def _security(self, request, fn, *args):
        if not perm("users.security")().has_permission(request, self):
            return Response(status=status.HTTP_403_FORBIDDEN)
        fn(self.get_object(), *args, request=request) if args else fn(self.get_object(), request=request)
        return Response(s.UserSerializer(self.get_object()).data)

    @action(detail=True, methods=["post"])
    def lock(self, request, pk=None):
        return self._security(request, user_services.set_active, False)

    @action(detail=True, methods=["post"])
    def unlock(self, request, pk=None):
        return self._security(request, user_services.set_active, True)

    @action(detail=True, methods=["post"], url_path="reset-2fa")
    def reset_2fa(self, request, pk=None):
        return self._security(request, user_services.reset_2fa)

    @action(detail=True, methods=["post"], url_path="end-sessions")
    def end_sessions(self, request, pk=None):
        return self._security(request, user_services.end_sessions)

    @action(detail=True, methods=["post"], url_path="send-password-reset")
    def send_password_reset(self, request, pk=None):
        if not perm("users.security")().has_permission(request, self):
            return Response(status=status.HTTP_403_FORBIDDEN)
        user_services.send_password_reset(self.get_object(), request._request)
        return Response({"sent": True})


class RoleViewSet(AdminViewSet):
    serializer_class = s.RoleSerializer
    view_perm = manage_perm = "roles.manage"
    pagination_class = None

    def get_queryset(self):
        return Role.objects.all()

    def perform_create(self, serializer):
        role = serializer.save(is_system=False)
        record(self.request, "role.create", "role", role.id, changes=serializer.data, category="security")

    def perform_update(self, serializer):
        role = serializer.save()
        record(self.request, "role.update", "role", role.id, changes=serializer.data, category="security")

    def perform_destroy(self, instance):
        if instance.is_system:
            raise ValidationError("Seeded roles cannot be deleted.")
        record(self.request, "role.delete", "role", instance.id, category="security")
        instance.delete()


class PlanViewSet(AdminViewSet):
    serializer_class = s.PlanSerializer
    view_perm, manage_perm = "plans.view", "plans.manage"
    pagination_class = None
    http_method_names = ["get", "post", "patch", "head", "options"]

    def get_queryset(self):
        return Plan.objects.prefetch_related("entitlements")

    def perform_create(self, serializer):
        plan = serializer.save()
        record(self.request, "plan.create", "plan", plan.id, changes={"key": plan.key})

    def perform_update(self, serializer):
        plan = serializer.save()
        record(self.request, "plan.update", "plan", plan.id, changes=self.request.data)


# ------------------------------------------------------------------ admin: settings
class SettingsView(TenantContextMixin, APIView):
    """GET / PATCH a settings screen: `general` (SA-21..27) or `system` (SA-16 base)."""

    def get_permissions(self):
        screen = self.kwargs.get("screen", "general")  # no kwargs while the OpenAPI schema is generated
        return [permissions.IsAuthenticated(), perm(f"settings.{screen}")()]

    def _keys(self, screen):
        groups = {g for g, (scr, _) in GROUPS.items() if scr == screen}
        return [st.key for st in SETTINGS if st.group in groups]

    @extend_schema(responses=dict)
    def get(self, request, screen):
        values = config.get_all()
        return Response({k: values[k] for k in self._keys(screen)})

    @extend_schema(request=dict, responses=dict)
    def patch(self, request, screen):
        allowed = set(self._keys(screen))
        unknown = set(request.data) - allowed
        if unknown:
            raise ValidationError({"unknown_keys": sorted(unknown)})
        changed = _django_errors(config.update, dict(request.data), user=request.user, request=request._request)
        return Response({"changed": sorted(changed)})


class UploadView(TenantContextMixin, APIView):
    """Image upload for settings and website content; returns the public URL to store in a setting / field."""

    parser_classes = [MultiPartParser]
    permission_classes = [permissions.IsAuthenticated, any_perm("settings.general", "cms.manage")]

    def post(self, request):
        upload = request.FILES.get("file")
        if not upload:
            raise ValidationError({"file": "Required."})
        url = _django_errors(save_public, upload, "uploads")
        record(request, "upload", "file", url)
        return Response({"url": url}, status=status.HTTP_201_CREATED)


# ------------------------------------------------------------------ admin: website content
class PageViewSet(
    TenantContextMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = s.PageSerializer
    queryset = Page.objects.prefetch_related("sections__section_type")
    pagination_class = None
    http_method_names = ["get", "patch", "post", "head", "options"]

    def get_permissions(self):
        key = "cms.view" if self.request.method in permissions.SAFE_METHODS else "cms.manage"
        return [permissions.IsAuthenticated(), perm(key)()]

    def perform_update(self, serializer):
        page = serializer.instance
        if "seo" in self.request.data:
            cms.update_seo(page, self.request.data["seo"], request=self.request._request)
        if "title" in self.request.data:
            page.title = self.request.data["title"]
            page.save(update_fields=["title", "updated_at"])

    @action(detail=True, methods=["post"])
    def reorder(self, request, pk=None):
        _django_errors(cms.reorder, self.get_object(), request.data.get("section_ids", []), request=request._request)
        return Response(s.PageSerializer(self.get_object()).data)


class SectionViewSet(TenantContextMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = s.SectionSerializer
    queryset = Section.objects.select_related("section_type", "page")

    def get_permissions(self):
        key = "cms.view" if self.request.method in permissions.SAFE_METHODS else "cms.manage"
        return [permissions.IsAuthenticated(), perm(key)()]

    def _done(self, section):
        return Response(s.SectionSerializer(section).data)

    @action(detail=True, methods=["put"])
    def draft(self, request, pk=None):
        section = _django_errors(
            cms.save_draft, self.get_object(), request.data.get("content", {}), request.user, request=request._request
        )
        return self._done(section)

    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        return self._done(cms.publish(self.get_object(), request.user, request=request._request))

    @action(detail=True, methods=["post"])
    def restore(self, request, pk=None):
        return self._done(
            cms.restore(self.get_object(), int(request.data["version"]), request.user, request=request._request)
        )

    @action(detail=True, methods=["post"])
    def visibility(self, request, pk=None):
        section = self.get_object()
        cms.set_visibility(section, bool(request.data.get("visible")), request=request._request)
        return self._done(section)


class EmailTemplateViewSet(AdminViewSet):
    serializer_class = s.EmailTemplateSerializer
    view_perm = manage_perm = "email_templates.manage"
    queryset = EmailTemplate.objects.all()
    pagination_class = None
    http_method_names = ["get", "patch", "head", "options"]

    def perform_update(self, serializer):
        tpl = serializer.save()
        record(self.request, "email_template.update", "email_template", tpl.id)


# ------------------------------------------------------------------ admin: logs, sessions
class _LogViewSet(TenantContextMixin, viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.IsAuthenticated, perm("logs.view")]


class AuditLogViewSet(_LogViewSet):
    serializer_class = s.AuditLogSerializer

    def get_queryset(self):
        qs = AuditLog.objects.all()
        p = self.request.query_params
        for field, lookup in (
            ("category", "category"),
            ("action", "action__icontains"),
            ("actor", "actor_email__icontains"),
            ("company", "company_id"),
            ("from", "created_at__date__gte"),
            ("to", "created_at__date__lte"),
        ):
            if p.get(field):
                qs = qs.filter(**{lookup: p[field]})
        return qs


class ApiLogViewSet(_LogViewSet):
    serializer_class = s.ApiRequestLogSerializer
    queryset = ApiRequestLog.objects.all()


class ErrorLogViewSet(_LogViewSet):
    serializer_class = s.ErrorLogSerializer
    queryset = ErrorLog.objects.all()


class SessionsView(TenantContextMixin, APIView):
    """SA-18: active sessions across users; staff with security permission can end them."""

    permission_classes = [permissions.IsAuthenticated, perm("security.manage")]

    def get(self, request):
        rows = UserSession.objects.select_related("user").order_by("-last_seen_at")[:500]
        return Response(
            [
                {
                    "id": r.id,
                    "user": r.user.email,
                    "ip": r.ip,
                    "user_agent": r.user_agent,
                    "created_at": r.created_at,
                    "last_seen_at": r.last_seen_at,
                }
                for r in rows
            ]
        )

    def delete(self, request):
        session = get_object_or_404(UserSession, id=request.query_params.get("id"))
        session.end()
        record(request, "session.end", "user", session.user_id, category="security")
        return Response(status=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------------ public (website + future app)
class PublicBrandingView(APIView):
    """SA-23: branding for the website, panels, widget and the Flutter app."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @extend_schema(responses=dict)
    def get(self, request):
        values = config.get_all()
        keys = [k for k in values if k.startswith(("general.", "contact.", "locale.", "seo."))]
        return Response({k: values[k] for k in keys})


class PublicPageView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @extend_schema(responses=dict)
    def get(self, request, key):
        page = get_object_or_404(Page, key=key)
        _, sections = cms.published_page(page.slug)
        return Response(
            {"key": page.key, "slug": page.slug, "title": page.title, "seo": page.seo, "sections": sections}
        )


class PublicPlansView(generics.ListAPIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    pagination_class = None
    serializer_class = s.PublicPlanSerializer

    def get_queryset(self):
        return Plan.objects.filter(is_public=True, status=Plan.ACTIVE)
