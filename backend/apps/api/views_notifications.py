"""REST API for team alerts (CP-03, NOTI-02, NOTI-03) and push devices (API-05, MOB-03).

notifications/                 GET ?unread=1 — own alerts, newest first
notifications/<id>/read/       POST — mark one read
notifications/read-all/        POST — mark all read
notifications/unread-count/    GET — {"unread": n} (the bell)
notifications/settings/        GET / PATCH {kind: [email, whatsapp, push]} — own alert channels
devices/                       GET own devices · POST {platform: web|android|ios, token, keys?, name?}
devices/<id>/                  DELETE · devices/remove/ POST {token} (log-out on the app)
push/config/                   GET {"web_push_public_key", "fcm"} — what the browser / app needs to subscribe
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications import alerts, push
from apps.notifications.models import Device, Notification
from apps.providers.adapters import ProviderError

from .base import TenantContextMixin


class NotificationSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = Notification
        fields = ["id", "kind", "kind_label", "title", "body", "url", "read_at", "data", "delivery", "created_at"]
        read_only_fields = fields


class NotificationViewSet(TenantContextMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        qs = Notification.objects.filter(company=self.request.company, user=self.request.user)
        if self.request.query_params.get("unread") == "1":
            qs = qs.filter(read_at__isnull=True)
        return qs

    @extend_schema(request=None, responses=dict)
    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        return Response({"updated": alerts.mark_read(request.user, request.company, [pk])})

    @extend_schema(request=None, responses=dict)
    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        return Response({"updated": alerts.mark_read(request.user, request.company)})

    @extend_schema(responses=dict)
    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        return Response({"unread": alerts.unread_count(request.user, request.company)})

    @extend_schema(request=dict, responses=dict)
    @action(detail=False, methods=["get", "patch"], url_path="settings")
    def preferences(self, request):
        if request.method == "PATCH":
            try:
                return Response(alerts.save_prefs(request.user, request.data))
            except DjangoValidationError as exc:
                raise ValidationError(exc.messages) from None
        return Response(alerts.prefs(request.user))


class DeviceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Device
        fields = ["id", "platform", "name", "last_used_at", "created_at"]
        read_only_fields = fields


class DeviceViewSet(mixins.ListModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    serializer_class = DeviceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Device.objects.filter(user=self.request.user)

    @extend_schema(request=dict, responses=DeviceSerializer)
    def create(self, request):
        try:
            device = push.register(
                request.user,
                request.data.get("platform", ""),
                request.data.get("token", ""),
                request.data.get("keys"),
                request.data.get("name") or request.headers.get("User-Agent", ""),
            )
        except ProviderError as exc:
            raise ValidationError(str(exc)) from None
        return Response(DeviceSerializer(device).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=dict, responses=dict)
    @action(detail=False, methods=["post"])
    def remove(self, request):
        return Response({"removed": push.unregister(request.user, request.data.get("token", ""))})


class PushConfigView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=dict)
    def get(self, request):
        return Response({"web_push_public_key": push.public_key(), "fcm": bool(push.provider("fcm"))})
