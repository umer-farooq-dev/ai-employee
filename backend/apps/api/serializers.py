from allauth.mfa.models import Authenticator
from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.audit.models import ApiRequestLog, AuditLog, ErrorLog
from apps.billing.models import Plan, PlanEntitlement
from apps.cms.models import Page, Section
from apps.notifications.models import EmailTemplate
from apps.rbac.models import Role
from apps.rbac.services import clean_permissions
from apps.tenancy.models import Company

User = get_user_model()


class CompanySerializer(serializers.ModelSerializer):
    plan = serializers.SlugRelatedField(slug_field="key", queryset=Plan.objects.all(), allow_null=True, required=False)

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
            "suspended_at",
            "suspended_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["slug", "status", "suspended_at", "suspended_reason"]


class OwnCompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "legal_name",
            "status",
            "email",
            "phone",
            "website",
            "city",
            "state",
            "timezone",
            "default_language",
            "created_at",
        ]
        read_only_fields = fields


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
        fields = ["id", "email", "full_name", "phone", "avatar", "timezone", "notification_prefs", "availability"]
        read_only_fields = ["email"]


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
