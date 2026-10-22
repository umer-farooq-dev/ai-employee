"""REST API for support tickets (CP-05): /api/v1/support/tickets/…

support/tickets/                 GET (?status=open|closed) · POST {subject, body, category, priority} (multipart "file")
support/tickets/<id>/            GET — with the conversation (staff notes left out)
support/tickets/<id>/reply/      POST {body} (multipart "file")
support/tickets/<id>/close/      POST
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.storage import signed_url
from apps.support import services as support
from apps.support.models import Ticket, TicketMessage

from .base import TenantContextMixin, perm


def _errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DjangoValidationError as exc:
        raise ValidationError(exc.messages) from None


class MessageSerializer(serializers.ModelSerializer):
    author = serializers.SerializerMethodField()
    attachment_url = serializers.SerializerMethodField()

    class Meta:
        model = TicketMessage
        fields = ["id", "author", "from_staff", "body", "attachment_name", "attachment_url", "created_at"]

    def get_author(self, obj):
        return "Support team" if obj.from_staff else (obj.author.full_name or obj.author.email if obj.author else "")

    def get_attachment_url(self, obj):
        return signed_url(obj.attachment_key) if obj.attachment_key else ""


class TicketSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    messages = serializers.SerializerMethodField()

    class Meta:
        model = Ticket
        fields = [
            "id",
            "number",
            "subject",
            "category",
            "priority",
            "status",
            "status_label",
            "last_reply_at",
            "created_at",
            "messages",
        ]
        read_only_fields = fields

    def get_messages(self, obj):
        if not self.context.get("detail"):
            return None
        return MessageSerializer(obj.messages.filter(internal=False).select_related("author"), many=True).data


class TicketViewSet(
    TenantContextMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = TicketSerializer

    def get_permissions(self):
        return [permissions.IsAuthenticated(), perm("company.view")()]

    def get_queryset(self):
        qs = Ticket.objects.filter(company=self.request.company)
        s = self.request.query_params.get("status")
        if s == "open":
            qs = qs.exclude(status__in=(Ticket.RESOLVED, Ticket.CLOSED))
        elif s == "closed":
            qs = qs.filter(status__in=(Ticket.RESOLVED, Ticket.CLOSED))
        return qs

    def retrieve(self, request, pk=None):
        return Response(TicketSerializer(self.get_object(), context={"detail": True}).data)

    @extend_schema(request=dict, responses=TicketSerializer)
    def create(self, request):
        t = _errors(
            support.open_ticket,
            request.company,
            request.user,
            request.data,
            request.FILES.get("file"),
            request._request,
        )
        return Response(TicketSerializer(t, context={"detail": True}).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=dict, responses=TicketSerializer)
    @action(detail=True, methods=["post"])
    def reply(self, request, pk=None):
        t = self.get_object()
        _errors(
            support.reply,
            t,
            request.user,
            request.data.get("body"),
            request.FILES.get("file"),
            request=request._request,
        )
        t.refresh_from_db()
        return Response(TicketSerializer(t, context={"detail": True}).data)

    @extend_schema(request=None, responses=TicketSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        t = _errors(support.set_status, self.get_object(), Ticket.CLOSED, request.user, request._request)
        return Response(TicketSerializer(t).data)
