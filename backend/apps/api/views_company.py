"""REST API for Phase 2: company profile, hours, onboarding, team, mobile OTP, invitations, public website data.

Company endpoints act on request.company (resolved from the signed-in user); ids in URLs are looked up inside it.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from apps.accounts import services as accounts
from apps.core.india import STATES
from apps.industries.models import Industry
from apps.platform_config import services as config
from apps.rbac.models import Role
from apps.tenancy import profile, team
from apps.tenancy.models import Invitation, Membership
from apps.website import services as website

from . import serializers as s
from .base import TenantContextMixin, perm


def _django_errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DjangoValidationError as exc:
        raise ValidationError(exc.messages) from None


class PublicFormThrottle(SimpleRateThrottle):
    """Website / app forms per IP (registration helpers, enquiries, invitations) — rate from Super Admin."""

    scope = "public_form"

    def get_rate(self):
        return config.get("security.api_rate_public_form")

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


# ------------------------------------------------------------------ own company (AUTH-09, CP-06, AUTH-10)
class OwnCompanyView(TenantContextMixin, generics.RetrieveUpdateAPIView):
    """GET: the signed-in user's company (also while pending, to show its status). PATCH: profile (company.manage)."""

    serializer_class = s.OwnCompanySerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_permissions(self):
        key = "company.view" if self.request.method in permissions.SAFE_METHODS else "company.manage"
        return [permissions.IsAuthenticated(), perm(key)()]

    def get_object(self):
        return self.request.company

    def perform_update(self, serializer):
        profile.update_profile(self.request.company, serializer.validated_data, request=self.request._request)


class CompanyHoursView(TenantContextMixin, APIView):
    """CP-06: business hours {mon: {open, close, closed}} and holidays [{date, name}]."""

    def get_permissions(self):
        key = "company.view" if self.request.method in permissions.SAFE_METHODS else "company.manage"
        return [permissions.IsAuthenticated(), perm(key)()]

    @extend_schema(responses=s.CompanyHoursSerializer)
    def get(self, request):
        c = request.company
        return Response({"business_hours": c.business_hours, "holidays": c.holidays})

    @extend_schema(request=s.CompanyHoursSerializer, responses=s.CompanyHoursSerializer)
    def put(self, request):
        data = s.CompanyHoursSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        c = _django_errors(
            profile.set_hours,
            request.company,
            data.validated_data.get("business_hours"),
            data.validated_data.get("holidays"),
            request=request._request,
        )
        return Response({"business_hours": c.business_hours, "holidays": c.holidays})


class OnboardingView(TenantContextMixin, APIView):
    permission_classes = [permissions.IsAuthenticated, perm("company.view")]

    @extend_schema(responses=dict)
    def get(self, request):
        data = profile.onboarding(request.company)
        for step in data["steps"]:
            step.pop("url_name")
        return Response(data)


# ------------------------------------------------------------------ team (AUTH-07)
class _TeamMixin(TenantContextMixin):
    def get_permissions(self):
        key = "team.view" if self.request.method in permissions.SAFE_METHODS else "team.manage"
        return [permissions.IsAuthenticated(), perm(key)()]


class TeamMemberViewSet(_TeamMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = s.MemberSerializer
    pagination_class = None

    def get_queryset(self):
        return Membership.objects.select_related("user", "role").order_by("created_at")

    def _other(self):
        membership = self.get_object()
        if membership.user_id == self.request.user.id:
            raise ValidationError("You cannot change your own access.")
        return membership

    @extend_schema(request=dict, responses=s.MemberSerializer)
    @action(detail=True, methods=["post"])
    def role(self, request, pk=None):
        membership = self._other()
        role = get_object_or_404(Role, scope="company", key=request.data.get("role"))
        _django_errors(team.change_role, membership, role, request=request._request)
        return Response(s.MemberSerializer(membership).data)

    @action(detail=True, methods=["post"])
    def deactivate(self, request, pk=None):
        membership = self._other()
        _django_errors(team.set_member_active, membership, False, request=request._request)
        return Response(s.MemberSerializer(membership).data)

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        membership = self._other()
        _django_errors(team.set_member_active, membership, True, request=request._request)
        return Response(s.MemberSerializer(membership).data)


class TransferOwnershipView(_TeamMixin, APIView):
    @extend_schema(request=dict, responses=dict)
    def post(self, request):
        new_owner = get_object_or_404(Membership, pk=request.data.get("member"))
        role = get_object_or_404(Role, scope="company", key=request.data.get("my_new_role"))
        _django_errors(
            team.transfer_ownership, request.company, request.user, new_owner, role, request=request._request
        )
        return Response({"transferred": True})


class InvitationViewSet(
    _TeamMixin, mixins.ListModelMixin, mixins.CreateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    serializer_class = s.InvitationSerializer
    pagination_class = None

    def get_queryset(self):
        return Invitation.objects.filter(status=Invitation.PENDING).select_related("role", "invited_by")

    def perform_create(self, serializer):
        d = serializer.validated_data
        serializer.instance = _django_errors(
            team.invite, self.request.company, d["email"], d["role"], self.request.user, request=self.request._request
        )

    def perform_destroy(self, instance):
        _django_errors(team.cancel, instance, request=self.request._request)

    @action(detail=True, methods=["post"])
    def resend(self, request, pk=None):
        return Response(s.InvitationSerializer(_django_errors(team.resend, self.get_object(), request._request)).data)


class InvitationPublicView(APIView):
    """GET: who invited whom. POST: accept — as the signed-in user, or by creating an account (full_name, password)."""

    permission_classes = [permissions.AllowAny]
    throttle_classes = [PublicFormThrottle]

    def _invitation(self, token):
        return _django_errors(team.invitation_for_token, token)

    @extend_schema(responses=dict)
    def get(self, request, token):
        inv = self._invitation(token)
        return Response(
            {
                "company": inv.company.name,
                "email": inv.email,
                "role": inv.role.name,
                "expires_at": inv.expires_at,
                "has_account": get_user_model().objects.filter(email=inv.email).exists(),
            }
        )

    @extend_schema(request=dict, responses=dict)
    def post(self, request, token):
        inv = self._invitation(token)
        if request.user.is_authenticated:
            _django_errors(team.accept, inv, request.user, request=request._request)
        else:
            password = request.data.get("password", "")
            from django.contrib.auth.password_validation import validate_password

            _django_errors(validate_password, password)
            _django_errors(
                team.accept_as_new_user, inv, str(request.data.get("full_name", "")), password, request._request
            )
        return Response({"accepted": True, "company": inv.company.name}, status=status.HTTP_201_CREATED)


# ------------------------------------------------------------------ mobile OTP (AUTH-02)
class PhoneOTPView(TenantContextMixin, APIView):
    """POST {"op": "send"} sends a code to the profile phone; POST {"op": "verify", "code": "123456"} verifies it."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=dict, responses=dict)
    def post(self, request):
        if request.data.get("op") == "send":
            _django_errors(accounts.send_phone_otp, request.user, request=request._request)
            return Response({"sent": True})
        _django_errors(accounts.verify_phone_otp, request.user, request.data.get("code", ""), request=request._request)
        return Response({"verified": True})


# ------------------------------------------------------------------ public (website + app)
class PublicIndustryViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    pagination_class = None
    serializer_class = s.PublicIndustrySerializer
    lookup_field = "key"

    def get_queryset(self):
        return Industry.objects.filter(is_active=True)


class PublicEnquiryView(APIView):
    """WEB-06 for the app and other clients (the website form posts to /enquiry/)."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = [PublicFormThrottle]

    @extend_schema(request=s.PublicEnquirySerializer, responses=dict)
    def post(self, request):
        data = s.PublicEnquirySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        enquiry = _django_errors(website.create_enquiry, data.validated_data, request._request)
        return Response({"id": enquiry.id}, status=status.HTTP_201_CREATED)


class RegistrationOptionsView(APIView):
    """Everything the app needs to draw the registration form (AUTH-01); the signup itself is
    POST /api/v1/auth/app/v1/auth/signup with the same fields as the website form."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    @extend_schema(responses=dict)
    def get(self, request):
        return Response(
            {
                "enabled": config.get("registration.enabled"),
                "approval_required": config.get("registration.approval_required"),
                "email_verification": config.get("registration.email_verification"),
                "mobile_otp_required": config.get("registration.mobile_otp_required"),
                "industries": s.PublicIndustrySerializer(Industry.objects.filter(is_active=True), many=True).data,
                "states": STATES,
                "business_sizes": config.get("registration.business_sizes"),
                "plans": s.PublicPlanSerializer(website.public_plans(), many=True).data,
                "fields": [
                    "email",
                    "password",
                    "business_name",
                    "full_name",
                    "phone",
                    "industry",
                    "city",
                    "state",
                    "business_size",
                    "website",
                    "gstin",
                    "accept_terms",
                    "plan",
                ],
            }
        )
