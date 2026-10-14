from allauth.mfa.models import Authenticator
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.audit.models import ApiRequestLog, AuditLog, ErrorLog
from apps.billing.models import Plan, PlanEntitlement
from apps.cms.models import Page, Section
from apps.industries.models import Industry
from apps.notifications.models import EmailTemplate
from apps.rbac.models import Role
from apps.rbac.services import clean_permissions
from apps.tenancy.models import Company, Invitation, Membership
from apps.website.models import Enquiry

User = get_user_model()


class CompanySerializer(serializers.ModelSerializer):
    plan = serializers.SlugRelatedField(slug_field="key", queryset=Plan.objects.all(), allow_null=True, required=False)
    industry = serializers.SlugRelatedField(
        slug_field="key", queryset=Industry.objects.all(), allow_null=True, required=False
    )

    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "legal_name",
            "slug",
            "status",
            "plan",
            "email",
            "phone",
            "website",
            "gstin",
            "address",
            "city",
            "state",
            "timezone",
            "default_language",
            "require_2fa",
            "industry",
            "business_size",
            "trial_ends_at",
            "terms_accepted_at",
            "approved_at",
            "rejected_reason",
            "suspended_at",
            "suspended_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "slug",
            "status",
            "suspended_at",
            "suspended_reason",
            "terms_accepted_at",
            "approved_at",
            "rejected_reason",
        ]


class OwnCompanySerializer(serializers.ModelSerializer):
    """AUTH-09: the signed-in user's company. Status, plan and approval fields are read-only."""

    plan = serializers.SlugRelatedField(slug_field="key", read_only=True)
    industry = serializers.SlugRelatedField(slug_field="key", read_only=True)

    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "legal_name",
            "status",
            "plan",
            "industry",
            "trial_ends_at",
            "rejected_reason",
            "logo",
            "email",
            "phone",
            "website",
            "gstin",
            "address",
            "city",
            "state",
            "timezone",
            "default_language",
            "created_at",
        ]
        read_only_fields = ["status", "plan", "industry", "trial_ends_at", "rejected_reason", "created_at"]

    def validate_gstin(self, value):
        from apps.core.india import validate_gstin

        value = (value or "").upper().strip()
        try:
            validate_gstin(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from None
        return value

    def validate_phone(self, value):
        from apps.accounts.models import phone_validator
        from apps.core.india import normalise_phone

        if not value:
            return value
        value = normalise_phone(value)
        try:
            phone_validator(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from None
        return value


class CompanyHoursSerializer(serializers.Serializer):
    business_hours = serializers.DictField(required=False)
    holidays = serializers.ListField(child=serializers.DictField(), required=False)


class IndustrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Industry
        fields = ["id", "key", "name", "short_description", "description", "icon", "image", "is_active", "sort_order"]


class PublicIndustrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Industry
        fields = ["key", "name", "short_description", "description", "icon", "image"]


class EnquirySerializer(serializers.ModelSerializer):
    industry = serializers.SlugRelatedField(slug_field="key", read_only=True)

    class Meta:
        model = Enquiry
        fields = [
            "id",
            "name",
            "business_name",
            "phone",
            "email",
            "industry",
            "message",
            "status",
            "notes",
            "source_url",
            "created_at",
        ]
        read_only_fields = ["name", "business_name", "phone", "email", "message", "source_url", "created_at"]


class PublicEnquirySerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150)
    business_name = serializers.CharField(max_length=200)
    phone = serializers.CharField(max_length=20)
    email = serializers.EmailField()
    industry = serializers.SlugRelatedField(slug_field="key", queryset=Industry.objects.filter(is_active=True))
    message = serializers.CharField(required=False, allow_blank=True, max_length=5000)


class MemberSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(source="user.email", read_only=True)
    full_name = serializers.CharField(source="user.full_name", read_only=True)
    role = serializers.SlugRelatedField(slug_field="key", read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "email", "full_name", "role", "status", "joined_at"]


class InvitationSerializer(serializers.ModelSerializer):
    role = serializers.SlugRelatedField(slug_field="key", queryset=Role.objects.filter(scope="company"))
    invited_by = serializers.EmailField(source="invited_by.email", read_only=True, default=None)

    class Meta:
        model = Invitation
        fields = ["id", "email", "role", "status", "invited_by", "expires_at", "created_at"]
        read_only_fields = ["status", "expires_at", "created_at"]


class UserSerializer(serializers.ModelSerializer):
    platform_role = serializers.SlugRelatedField(
        slug_field="key", queryset=Role.objects.filter(scope="platform"), allow_null=True, required=False
    )
    has_2fa = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "phone",
            "is_active",
            "is_staff",
            "platform_role",
            "has_2fa",
            "date_joined",
            "last_login",
        ]
        read_only_fields = ["date_joined", "last_login"]

    def get_has_2fa(self, obj):
        return Authenticator.objects.filter(user=obj, type=Authenticator.Type.TOTP).exists()


class MeSerializer(serializers.ModelSerializer):
    """AUTH-08 profile. Email changes go through the verified email flow, not here."""

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "full_name",
            "phone",
            "phone_verified_at",
            "avatar",
            "timezone",
            "notification_prefs",
            "availability",
        ]
        read_only_fields = ["email", "phone_verified_at"]

    def update(self, instance, validated_data):
        if "phone" in validated_data and validated_data["phone"] != instance.phone:
            instance.phone_verified_at = None  # a new number must be verified again (AUTH-02)
        return super().update(instance, validated_data)


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["id", "scope", "key", "name", "description", "permissions", "is_system"]
        read_only_fields = ["is_system"]

    def validate(self, attrs):
        scope = attrs.get("scope", getattr(self.instance, "scope", None))
        if "permissions" in attrs:
            attrs["permissions"] = clean_permissions(scope, attrs["permissions"])
        return attrs


class EntitlementSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanEntitlement
        fields = ["key", "limit_value", "overage_price_paise", "enforcement"]


class PlanSerializer(serializers.ModelSerializer):
    entitlements = EntitlementSerializer(many=True, required=False)

    class Meta:
        model = Plan
        fields = [
            "id",
            "key",
            "name",
            "description",
            "price_monthly_paise",
            "price_yearly_paise",
            "gst_rate",
            "trial_days",
            "is_public",
            "is_custom",
            "features",
            "status",
            "sort_order",
            "entitlements",
        ]

    def _save_entitlements(self, plan, rows):
        for row in rows:
            PlanEntitlement.objects.update_or_create(plan=plan, key=row["key"], defaults=row)

    def create(self, validated):
        rows = validated.pop("entitlements", [])
        plan = super().create(validated)
        self._save_entitlements(plan, rows)
        return plan

    def update(self, instance, validated):
        rows = validated.pop("entitlements", None)
        plan = super().update(instance, validated)
        if rows is not None:
            self._save_entitlements(plan, rows)
        return plan


class PublicPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ["key", "name", "description", "price_monthly_paise", "price_yearly_paise", "is_custom", "features"]


class SectionSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="section_type.key", read_only=True)
    schema = serializers.JSONField(source="section_type.schema", read_only=True)
    has_draft = serializers.BooleanField(read_only=True)

    class Meta:
        model = Section
        fields = [
            "id",
            "type",
            "schema",
            "sort_order",
            "is_visible",
            "anchor_id",
            "content",
            "draft_content",
            "has_draft",
            "version",
            "published_at",
        ]
        read_only_fields = ["sort_order", "is_visible", "content", "draft_content", "version", "published_at"]


class PageSerializer(serializers.ModelSerializer):
    sections = SectionSerializer(many=True, read_only=True)

    class Meta:
        model = Page
        fields = ["id", "key", "slug", "title", "seo", "is_system", "sections"]
        read_only_fields = ["key", "slug", "is_system"]


class EmailTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailTemplate
        fields = ["id", "key", "name", "subject", "body_html", "variables", "is_active", "updated_at"]
        read_only_fields = ["key", "variables"]


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = [
            "id",
            "created_at",
            "company",
            "actor_email",
            "impersonator_email",
            "category",
            "action",
            "entity_type",
            "entity_id",
            "changes",
            "ip",
            "request_id",
        ]


class ApiRequestLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApiRequestLog
        fields = "__all__"


class ErrorLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ErrorLog
        fields = "__all__"
