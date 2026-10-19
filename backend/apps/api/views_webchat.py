"""REST API for the website chat widget (M16) and the shared inbox (WA-06, CHAT-06).

Public, for the widget on the company's website (/public/v1/chat/<key>/ …, CHAT-05: allowed websites, rate limits,
bot protection; the visitor's conversation is named by a signed token in the X-Chat-Token header):
  GET   <key>/              appearance, texts per language, actions
  POST  <key>/sessions/     {language, page} → token + opening messages
  GET   <key>/messages/     ?after=<message id> → new messages + who answers now
  POST  <key>/messages/     {text} → the AI's answer (none while a person handles the chat)
  POST  <key>/human/        talk to a person (handoff)
  POST  <key>/contact/      {kind: enquiry|callback, name, phone, email, message}
  POST  <key>/end/
Company (/api/v1/):
  ai-employees/<id>/widget/  GET, PATCH (settings + embed snippet)
  inbox/                     ?view=open|waiting|mine|ai|ended&channel=&q=
  inbox/<id>/                ?after=<message id>;  take-over | hand-back | reply {text} | assign {user} | end   POST
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Max, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, Throttled, ValidationError
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from apps.agents import inbox
from apps.agents.models import AIEmployee, Conversation, Message
from apps.platform_config import services as config
from apps.rbac.services import has_perm
from apps.tenancy.context import activate, deactivate
from apps.webchat import services as chat
from apps.webchat.models import ChatWidget

from .base import TenantContextMixin, perm


def _errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DjangoValidationError as exc:
        raise ValidationError(exc.messages) from None


# ------------------------------------------------------------------ public widget API
class ChatSessionThrottle(SimpleRateThrottle):
    scope = "chat_sessions"

    def get_rate(self):
        return config.get("chat.rate_sessions")

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class ChatMessageThrottle(SimpleRateThrottle):
    scope = "chat_messages"

    def get_rate(self):
        return config.get("chat.rate_messages")

    def get_cache_key(self, request, view):
        token = request.headers.get("X-Chat-Token") or self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": token[-48:]}


class WidgetView(APIView):
    """Resolves the widget from the key, checks the page's website and sets the company context."""

    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    throttle_classes = []
    write_throttles = ()

    def initial(self, request, *args, **kwargs):
        self.widget = chat.resolve(kwargs.get("key"))
        self.origin = request.headers.get("Origin") or ""
        if self.widget is None:
            raise NotFound("This chat is not available.")
        if not chat.origin_allowed(self.widget, self.origin or request.headers.get("Referer", "")):
            raise PermissionDenied("This website may not show this chat.")
        self._tenant_tokens = activate(self.widget.company_id)
        super().initial(request, *args, **kwargs)

    def get_throttles(self):
        if self.request.method == "POST":
            return [t() for t in self.write_throttles]
        return []

    def throttled(self, request, wait):
        raise Throttled(wait, detail="Too many messages. Please wait a moment.")

    def options(self, request, *args, **kwargs):
        return Response(status=status.HTTP_204_NO_CONTENT)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        tokens = getattr(self, "_tenant_tokens", None)
        if tokens:
            deactivate(tokens)
            self._tenant_tokens = None
        origin = request.headers.get("Origin")
        if origin and getattr(self, "widget", None) and chat.origin_allowed(self.widget, origin):
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Content-Type, X-Chat-Token"
            response["Access-Control-Max-Age"] = "600"
        response["Vary"] = "Origin"
        return response

    def conversation(self, request):
        conv = chat.conversation_for(self.widget, request.headers.get("X-Chat-Token"))
        if conv is None:
            raise NotFound("Chat not found. Start a new chat.")
        return conv

    def snapshot(self, conv, after=""):
        return {**chat.state(conv), "messages": chat.messages_after(conv, after)}


class PublicChatConfigView(WidgetView):
    @extend_schema(responses=dict)
    def get(self, request, key):
        return Response(chat.public_config(self.widget))


class PublicChatSessionView(WidgetView):
    write_throttles = (ChatSessionThrottle,)

    @extend_schema(request=dict, responses=dict)
    def post(self, request, key):
        if request.data.get("website"):  # honeypot: people never see this field
            raise ValidationError("Not accepted.")
        conv = _errors(chat.start, self.widget, request.data.get("language", ""), request.data.get("page", ""))
        return Response({"token": chat.token_for(conv), **self.snapshot(conv)}, status=status.HTTP_201_CREATED)


class PublicChatMessagesView(WidgetView):
    write_throttles = (ChatMessageThrottle,)

    @extend_schema(responses=dict)
    def get(self, request, key):
        return Response(self.snapshot(self.conversation(request), request.query_params.get("after", "")))

    @extend_schema(request=dict, responses=dict)
    def post(self, request, key):
        conv = self.conversation(request)
        _errors(chat.send, conv, request.data.get("text", ""))
        conv.refresh_from_db()
        return Response(self.snapshot(conv, request.data.get("after", "")))


class PublicChatHumanView(WidgetView):
    write_throttles = (ChatMessageThrottle,)

    @extend_schema(request=dict, responses=dict)
    def post(self, request, key):
        if not self.widget.action_on("human"):
            raise ValidationError("Not available.")
        conv = self.conversation(request)
        _errors(chat.ask_for_person, conv)
        conv.refresh_from_db()
        return Response(self.snapshot(conv, request.data.get("after", "")))


class PublicChatContactView(WidgetView):
    write_throttles = (ChatSessionThrottle,)

    @extend_schema(request=dict, responses=dict)
    def post(self, request, key):
        if request.data.get("website"):
            raise ValidationError("Not accepted.")
        conv = chat.conversation_for(self.widget, request.headers.get("X-Chat-Token"))
        _errors(chat.contact, self.widget, conv, request.data.get("kind", ""), request.data)
        return Response(self.snapshot(conv, request.data.get("after", "")) if conv else {"ok": True})


class PublicChatEndView(WidgetView):
    write_throttles = (ChatMessageThrottle,)

    @extend_schema(request=dict, responses=dict)
    def post(self, request, key):
        conv = self.conversation(request)
        if conv.status == Conversation.ACTIVE:
            inbox.close(conv)
        return Response({"status": "ended"})


# ------------------------------------------------------------------ company: widget settings (CHAT-01 / CHAT-02)
class WidgetSerializer(serializers.ModelSerializer):
    snippet = serializers.SerializerMethodField()

    class Meta:
        model = ChatWidget
        fields = [
            "id",
            "employee",
            "key",
            "is_enabled",
            "title",
            "subtitle",
            "launcher_text",
            "greetings",
            "avatar",
            "color",
            "position",
            "language",
            "allowed_domains",
            "actions",
            "snippet",
            "updated_at",
        ]
        read_only_fields = fields

    def get_snippet(self, obj):
        return chat.snippet(obj)


class EmployeeWidgetView(TenantContextMixin, APIView):
    def get_permissions(self):
        key = "ai_employees.view" if self.request.method in permissions.SAFE_METHODS else "ai_employees.manage"
        return [permissions.IsAuthenticated(), perm(key)()]

    def _widget(self, request, pk):
        employee = get_object_or_404(AIEmployee, pk=pk, company=request.company)
        return chat.widget_for(employee)

    @extend_schema(responses=WidgetSerializer)
    def get(self, request, pk):
        return Response(WidgetSerializer(self._widget(request, pk)).data)

    @extend_schema(request=dict, responses=WidgetSerializer)
    def patch(self, request, pk):
        widget = _errors(chat.save_widget, self._widget(request, pk), request.data, request.user, request._request)
        return Response(WidgetSerializer(widget).data)


# ------------------------------------------------------------------ company: shared inbox (WA-06, CHAT-06)
class InboxSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(source="employee.name", read_only=True)
    lead_reference = serializers.CharField(source="lead.reference", read_only=True, default="")
    lead_name = serializers.CharField(source="lead.name", read_only=True, default="")
    lead_score = serializers.CharField(source="lead.score_label", read_only=True, default="")
    assigned_name = serializers.SerializerMethodField()
    last_message_at = serializers.DateTimeField(read_only=True, default=None)
    preview = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id",
            "channel",
            "status",
            "handled_by",
            "assigned_user",
            "assigned_name",
            "employee",
            "employee_name",
            "lead",
            "lead_reference",
            "lead_name",
            "lead_score",
            "customer",
            "language",
            "summary",
            "intent",
            "started_at",
            "ended_at",
            "last_message_at",
            "preview",
        ]
        read_only_fields = fields

    def get_assigned_name(self, obj):
        return (obj.assigned_user.full_name or obj.assigned_user.email) if obj.assigned_user else ""

    def get_preview(self, obj):
        text = getattr(obj, "last_text", None)
        return {"role": obj.last_role, "text": text[:140]} if text else None


VIEWS = ("open", "waiting", "mine", "ai", "ended", "all")


def inbox_queryset(request, view="open", channel="", q=""):
    """The conversations of the inbox, newest activity first (the panel page uses the same filters)."""
    last = Message.objects.filter(conversation=OuterRef("pk"), role__in=("customer", "ai", "human")).order_by(
        "-created_at"
    )
    qs = (
        Conversation.objects.filter(company=request.company, channel__in=Conversation.CHAT_CHANNELS, is_test=False)
        .select_related("employee", "lead", "assigned_user")
        .annotate(
            last_message_at=Max("messages__created_at"),
            last_text=Subquery(last.values("content")[:1]),
            last_role=Subquery(last.values("role")[:1]),
        )
        .order_by("-last_message_at")
    )
    if view == "open":
        qs = qs.filter(status=Conversation.ACTIVE)
    elif view == "waiting":
        qs = qs.filter(status=Conversation.ACTIVE, handled_by=Conversation.WAITING)
    elif view == "mine":
        qs = qs.filter(status=Conversation.ACTIVE, assigned_user=request.user)
    elif view == "ai":
        qs = qs.filter(status=Conversation.ACTIVE, handled_by=Conversation.AI)
    elif view == "ended":
        qs = qs.filter(status=Conversation.ENDED)
    if channel in Conversation.CHAT_CHANNELS:
        qs = qs.filter(channel=channel)
    if q:
        qs = qs.filter(
            Q(lead__name__icontains=q)
            | Q(lead__phone__icontains=q)
            | Q(customer__name__icontains=q)
            | Q(messages__content__icontains=q)
        ).distinct()
    return qs


class InboxViewSet(TenantContextMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = InboxSerializer

    def get_permissions(self):
        key = "conversations.view" if self.action in ("list", "retrieve") else "handoffs.receive"
        return [permissions.IsAuthenticated(), perm(key)()]

    def get_queryset(self):
        p = self.request.query_params
        view = p.get("view") if p.get("view") in VIEWS else ("all" if self.action != "list" else "open")
        return inbox_queryset(self.request, view, p.get("channel", ""), p.get("q", "").strip())

    def retrieve(self, request, *args, **kwargs):
        conv = self.get_object()
        if conv.handled_by == Conversation.WAITING:
            chat.state(conv)  # skips an agent who did not answer in time
            conv.refresh_from_db()
        return Response(
            {
                **InboxSerializer(conv).data,
                "messages": chat.messages_after(conv, request.query_params.get("after", "")),
                "can_answer": has_perm(request.user, "handoffs.receive", request.company),
            }
        )

    def _done(self, conv):
        conv = self.get_queryset().get(pk=conv.pk)
        after = self.request.data.get("after", "")
        return Response({**InboxSerializer(conv).data, "messages": chat.messages_after(conv, after)})

    @action(detail=True, methods=["post"], url_path="take-over")
    def take_over(self, request, pk=None):
        conv = self.get_object()
        _errors(inbox.take_over, conv, request.user, request._request)
        return self._done(conv)

    @action(detail=True, methods=["post"], url_path="hand-back")
    def hand_back(self, request, pk=None):
        conv = self.get_object()
        _errors(inbox.hand_back, conv, request.user, request._request)
        return self._done(conv)

    @action(detail=True, methods=["post"])
    def reply(self, request, pk=None):
        conv = self.get_object()
        _errors(inbox.reply, conv, request.user, request.data.get("text", ""), request._request)
        return self._done(conv)

    @action(detail=True, methods=["post"])
    def assign(self, request, pk=None):
        from apps.crm.services import members

        conv = self.get_object()
        uid = str(request.data.get("user") or "")
        member = next((u for u in members(request.company) if str(u.pk) == uid), None) if uid else None
        if uid and member is None:
            raise ValidationError({"user": "Choose a member of your team."})
        _errors(inbox.assign, conv, member, request.user, request._request)
        return self._done(conv)

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        conv = self.get_object()
        _errors(inbox.close, conv, request.user, request._request)
        return self._done(conv)
