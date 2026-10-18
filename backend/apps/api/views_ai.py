"""REST API for AI, speech and telephony providers, model per task, languages and voices (SA-09, SA-10, SA-11,
ENG-09). Used by Super Admin → AI Settings / Voice Settings / Languages & Voices and the future app.

/api/v1/admin/ai-providers/            list (?group=llm|voice), create   (keys are write-only, never returned)
/api/v1/admin/ai-providers/<id>/       read, update, delete
/api/v1/admin/ai-providers/<id>/active/  {"is_active": bool}
/api/v1/admin/ai-providers/<id>/test/    connection test → health + model list
/api/v1/admin/ai-providers/<id>/voices/  ?locale=hi-IN → the vendor's voices (catalogue import)
/api/v1/admin/ai-routes/               all tasks with their fallback chain
/api/v1/admin/ai-routes/<task>/        PUT {"routes": [{"provider", "model", "params"}]} in priority order
/api/v1/admin/languages/               list, create; <id>/ read, update, delete
/api/v1/admin/languages/<id>/routes/   PUT {"kind": "stt"|"tts", "routes": [{"provider", "model", "voice", "params"}]}
/api/v1/admin/voices/                  list (?language=hi&provider=sarvam), create; <id>/ read, update, delete
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.providers import services, vendors
from apps.providers.models import (
    CAPABILITIES,
    LANGUAGE_TEXTS,
    LLM_CAPABILITIES,
    SCRIPTS,
    TASKS,
    VOICE_CAPABILITIES,
    Language,
    ModelRoute,
    Provider,
    SpeechRoute,
    Voice,
)
from apps.rbac.services import has_perm

from .base import AdminViewSet, TenantContextMixin, any_perm, perm

PERM = "ai_providers.manage"
VOICE_PERM = "voice_settings.manage"
LLM_CAPS = {c for c, _ in LLM_CAPABILITIES}
VOICE_CAPS = {c for c, _ in VOICE_CAPABILITIES}


def allowed_caps(user):
    """Capabilities this staff member may manage: AI Settings (LLM) and / or Voice Settings (speech, telephony)."""
    return (LLM_CAPS if has_perm(user, PERM) else set()) | (VOICE_CAPS if has_perm(user, VOICE_PERM) else set())


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
    vendor = serializers.ChoiceField(choices=[("", "—")] + vendors.VENDOR_CHOICES, required=False, allow_blank=True)
    config = serializers.DictField(child=serializers.CharField(allow_blank=True), required=False)

    class Meta:
        model = Provider
        fields = [
            "id",
            "key",
            "name",
            "description",
            "adapter",
            "vendor",
            "config",
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
        """Tasks / languages routed to this provider: {"chat_dialog": 1, "stt": 2, …} (the chips on the vendor card)."""
        out = {}
        for route in obj.routes.all():
            out[route.task] = out.get(route.task, 0) + 1
        for route in obj.speech_routes.all():
            out[route.kind] = out.get(route.kind, 0) + 1
        return out

    def validate_key(self, value):
        if self.instance and value != self.instance.key:
            raise ValidationError("The key cannot be changed.")
        return value


class ProviderViewSet(TenantContextMixin, viewsets.ModelViewSet):
    serializer_class = ProviderSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        return [permissions.IsAuthenticated(), any_perm(PERM, VOICE_PERM)()]

    def get_queryset(self):
        caps = allowed_caps(self.request.user)
        group = self.request.query_params.get("group")
        if group in ("llm", "voice"):
            caps &= LLM_CAPS if group == "llm" else VOICE_CAPS
        rows = Provider.objects.prefetch_related("routes", "speech_routes")
        return rows.filter(pk__in=[p.pk for p in rows.only("pk", "capabilities") if set(p.capabilities) & caps])

    def _check_caps(self, instance, capabilities):
        """Only capabilities this staff member manages may be added or removed (a shared vendor keeps the rest)."""
        changed = set(capabilities) ^ set(instance.capabilities if instance else [])
        if not changed <= allowed_caps(self.request.user):
            raise PermissionDenied("You cannot manage these provider capabilities.")

    def _save(self, serializer, instance):
        data = dict(serializer.validated_data)
        if "capabilities" in data:
            self._check_caps(instance, data["capabilities"])
        if "available_models" in data:
            data["available_models"] = [dict(m) for m in data["available_models"]]
        provider = _errors(services.save_provider, instance, data, self.request.user, self.request._request)
        return Response(ProviderSerializer(Provider.objects.get(pk=provider.pk)).data)

    @action(detail=True, methods=["get"])
    def voices(self, request, pk=None):
        provider = self.get_object()
        return Response(_errors(services.provider_voices, provider, request.query_params.get("locale", "")))

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


# ------------------------------------------------------------------ SA-11 languages & voices
class SpeechRouteSerializer(serializers.ModelSerializer):
    provider_key = serializers.CharField(source="provider.key", read_only=True)
    provider_name = serializers.CharField(source="provider.name", read_only=True)
    provider_active = serializers.BooleanField(source="provider.is_active", read_only=True)
    voice_name = serializers.CharField(source="voice.name", read_only=True, default="")

    class Meta:
        model = SpeechRoute
        fields = [
            "kind",
            "provider",
            "provider_key",
            "provider_name",
            "provider_active",
            "model",
            "voice",
            "voice_name",
            "params",
            "priority",
        ]


class LanguageSerializer(serializers.ModelSerializer):
    texts = serializers.DictField(required=False)
    routes = SpeechRouteSerializer(many=True, read_only=True)
    voice_count = serializers.SerializerMethodField()

    class Meta:
        model = Language
        fields = [
            "id",
            "code",
            "name",
            "native_name",
            "locale",
            "script",
            "texts",
            "is_active",
            "sort_order",
            "routes",
            "voice_count",
        ]

    def get_voice_count(self, obj):
        return len([v for v in obj.voices.all() if v.is_active])


class LanguageViewSet(AdminViewSet):
    view_perm = manage_perm = VOICE_PERM
    serializer_class = LanguageSerializer
    queryset = Language.objects.prefetch_related("routes__provider", "routes__voice", "voices")
    pagination_class = None
    http_method_names = ["get", "post", "patch", "put", "delete", "head", "options"]

    def _out(self, language):
        return Response(LanguageSerializer(self.get_queryset().get(pk=language.pk)).data)

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        lang = _errors(services.save_language, None, dict(s.validated_data), request.user, request._request)
        response = self._out(lang)
        response.status_code = status.HTTP_201_CREATED
        return response

    def partial_update(self, request, *args, **kwargs):
        s = self.get_serializer(self.get_object(), data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        return self._out(
            _errors(services.save_language, s.instance, dict(s.validated_data), request.user, request._request)
        )

    def update(self, request, *args, **kwargs):  # PUT behaves like PATCH (only sent fields change)
        return self.partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        _errors(services.delete_language, self.get_object(), request.user, request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["put"])
    def routes(self, request, pk=None):
        rows = request.data.get("routes")
        if not isinstance(rows, list):
            raise ValidationError({"routes": "A list is required."})
        language = self.get_object()
        _errors(services.save_speech_routes, language, request.data.get("kind"), rows, request.user, request._request)
        return self._out(language)


class VoiceSerializer(serializers.ModelSerializer):
    language = serializers.SlugRelatedField(slug_field="code", queryset=Language.objects.all())
    provider = serializers.SlugRelatedField(slug_field="key", queryset=Provider.objects.all())
    provider_name = serializers.CharField(source="provider.name", read_only=True)

    class Meta:
        model = Voice
        fields = [
            "id",
            "language",
            "provider",
            "provider_name",
            "provider_voice_id",
            "name",
            "gender",
            "style",
            "sample",
            "is_active",
            "sort_order",
        ]


class VoiceViewSet(AdminViewSet):
    view_perm = manage_perm = VOICE_PERM
    serializer_class = VoiceSerializer
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        rows = Voice.objects.select_related("language", "provider")
        q = self.request.query_params
        if q.get("language"):
            rows = rows.filter(language__code=q["language"])
        if q.get("provider"):
            rows = rows.filter(provider__key=q["provider"])
        return rows

    def _save(self, instance, data):
        if "language" in data:
            data["language"] = data["language"].code
        if "provider" in data:
            data["provider"] = data["provider"].key
        voice = _errors(services.save_voice, instance, data, self.request.user, self.request._request)
        return Response(VoiceSerializer(voice).data)

    def create(self, request, *args, **kwargs):
        s = self.get_serializer(data=request.data)
        s.is_valid(raise_exception=True)
        response = self._save(None, dict(s.validated_data))
        response.status_code = status.HTTP_201_CREATED
        return response

    def partial_update(self, request, *args, **kwargs):
        s = self.get_serializer(self.get_object(), data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        return self._save(s.instance, dict(s.validated_data))

    def destroy(self, request, *args, **kwargs):
        services.delete_voice(self.get_object(), request.user, request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)


def language_page_data():
    """Everything the Languages & Voices screen needs (also the API's option lists)."""
    return {
        "texts": [{"key": k, "label": label} for k, label in LANGUAGE_TEXTS],
        "scripts": [{"key": k, "label": label} for k, label in SCRIPTS],
        "genders": [{"key": k, "label": label} for k, label in Voice.GENDERS],
    }
