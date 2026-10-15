"""REST API for AI providers and model per task (SA-09, ENG-09). Used by Super Admin → AI Settings and the future app.

/api/v1/admin/ai-providers/            list, create          (keys are write-only, never returned)
/api/v1/admin/ai-providers/<id>/       read, update, delete
/api/v1/admin/ai-providers/<id>/active/  {"is_active": bool}
/api/v1/admin/ai-providers/<id>/test/    connection test → health + model list
/api/v1/admin/ai-routes/               all tasks with their fallback chain
/api/v1/admin/ai-routes/<task>/        PUT {"routes": [{"provider", "model", "params"}]} in priority order
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.providers import services
from apps.providers.models import CAPABILITIES, TASKS, ModelRoute, Provider

from .base import TenantContextMixin, perm

PERM = "ai_providers.manage"


def _errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DjangoValidationError as exc:
        raise ValidationError(exc.messages) from None


class AIModelSerializer(serializers.Serializer):
    id = serializers.CharField(max_length=200)
    input_cost = serializers.FloatField(min_value=0, required=False, default=0)
    output_cost = serializers.FloatField(min_value=0, required=False, default=0)


class ProviderSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(write_only=True, required=False, allow_blank=True, trim_whitespace=True)
    remove_key = serializers.BooleanField(write_only=True, required=False)
    available_models = AIModelSerializer(many=True, required=False)
    capabilities = serializers.ListField(
        child=serializers.ChoiceField(choices=[c for c, _ in CAPABILITIES]), required=False
    )
    has_key = serializers.BooleanField(read_only=True)
    usage = serializers.SerializerMethodField()

    class Meta:
        model = Provider
        fields = [
            "id",
            "key",
            "name",
            "description",
            "adapter",
            "base_url",
            "logo",
            "capabilities",
            "available_models",
            "test_only",
            "is_active",
            "sort_order",
            "health",
            "has_key",
            "api_key",
            "remove_key",
            "usage",
        ]
        read_only_fields = ["is_active", "health"]

    def get_usage(self, obj):
        """Tasks routed to this provider: {"chat_dialog": 1, …} (the chips on the vendor card)."""
        out = {}
        for route in obj.routes.all():
            out[route.task] = out.get(route.task, 0) + 1
        return out

    def validate_key(self, value):
        if self.instance and value != self.instance.key:
            raise ValidationError("The key cannot be changed.")
        return value


class ProviderViewSet(TenantContextMixin, viewsets.ModelViewSet):
    serializer_class = ProviderSerializer
    queryset = Provider.objects.prefetch_related("routes")
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        return [permissions.IsAuthenticated(), perm(PERM)()]

    def _save(self, serializer, instance):
        data = dict(serializer.validated_data)
        if "available_models" in data:
            data["available_models"] = [dict(m) for m in data["available_models"]]
        provider = _errors(services.save_provider, instance, data, self.request.user, self.request._request)
        return Response(ProviderSerializer(Provider.objects.get(pk=provider.pk)).data)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        response = self._save(serializer, None)
        response.status_code = status.HTTP_201_CREATED
        return response

    def partial_update(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        return self._save(serializer, serializer.instance)

    def destroy(self, request, *args, **kwargs):
        services.delete_provider(self.get_object(), request.user, request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def active(self, request, pk=None):
        provider = _errors(
            services.set_active, self.get_object(), bool(request.data.get("is_active")), request.user, request._request
        )
        return Response(ProviderSerializer(provider).data)

    @action(detail=True, methods=["post"])
    def test(self, request, pk=None):
        health, models = services.test_connection(self.get_object())
        return Response({"health": health, "models": models})


class RouteSerializer(serializers.ModelSerializer):
    provider_key = serializers.CharField(source="provider.key", read_only=True)
    provider_name = serializers.CharField(source="provider.name", read_only=True)

    class Meta:
        model = ModelRoute
        fields = ["provider", "provider_key", "provider_name", "model", "params", "priority"]


class RoutesView(TenantContextMixin, APIView):
    def get_permissions(self):
        return [permissions.IsAuthenticated(), perm(PERM)()]

    def get(self, request):
        chains = services.routes()
        return Response(
            [
                {"task": key, "label": label, "capability": cap, "routes": RouteSerializer(chains[key], many=True).data}
                for key, label, cap in TASKS
            ]
        )

    def put(self, request, task):
        if task not in {k for k, _, _ in TASKS}:
            raise NotFound("Unknown task.")
        rows = request.data.get("routes")
        if not isinstance(rows, list):
            raise ValidationError({"routes": "A list is required."})
        saved = _errors(services.save_routes, task, rows, request.user, request._request)
        return Response(RouteSerializer(saved, many=True).data)
