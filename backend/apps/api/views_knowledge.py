"""REST API for the knowledge base (KB-01 … KB-11). /api/v1/kb/…

kb/sources/            list (type, approval, status), create (multipart for files)
kb/sources/<id>/       read, update (title, category, body, crawl, schedule, employees), delete (KB-07)
kb/sources/<id>/approve|unapprove|reprocess   POST
kb/faqs/               list (?source=), create;  kb/faqs/<id>/ update, delete;  kb/faqs/<id>/approve  POST
kb/faqs/import/        POST multipart {source, file}
kb/test-query/         POST {"question", "employee"} → answer + exact sources (KB-09)
kb/unanswered/         list (?status=);  kb/unanswered/<id>/resolve  POST (KB-10)
"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import mixins, permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.models import AIEmployee
from apps.core.storage import signed_url
from apps.knowledge import services as kb
from apps.knowledge.models import FAQ, Source, UnansweredQuestion

from .base import TenantContextMixin, perm


def _errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DjangoValidationError as exc:
        raise ValidationError(exc.messages) from None


def _perms(view, read="knowledge.view", write="knowledge.manage"):
    return [permissions.IsAuthenticated(), perm(read if view.request.method in permissions.SAFE_METHODS else write)()]


class SourceSerializer(serializers.ModelSerializer):
    employees = serializers.PrimaryKeyRelatedField(many=True, read_only=True)
    documents = serializers.IntegerField(source="documents.count", read_only=True)
    chunks = serializers.IntegerField(source="chunks.count", read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Source
        fields = [
            "id",
            "type",
            "title",
            "uri",
            "file_name",
            "file_size",
            "file_url",
            "body",
            "category",
            "language",
            "crawl",
            "status",
            "error",
            "approval",
            "approved_by",
            "approved_at",
            "employees",
            "sync_schedule",
            "last_synced_at",
            "processed_at",
            "documents",
            "chunks",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_file_url(self, obj):
        return signed_url(obj.file_key) if obj.file_key else ""


class FAQSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQ
        fields = ["id", "source", "question", "answer", "language", "approval", "sort_order", "created_at"]
        read_only_fields = fields


class UnansweredSerializer(serializers.ModelSerializer):
    class Meta:
        model = UnansweredQuestion
        fields = [
            "id",
            "employee",
            "normalized_question",
            "example_text",
            "count",
            "status",
            "conversation",
            "last_seen_at",
            "created_at",
        ]
        read_only_fields = fields


def _data(request):
    """Form posts send lists as repeated keys (employees, include, exclude)."""
    if hasattr(request.data, "getlist"):
        data = {k: request.data.get(k) for k in request.data}
        for key in ("employees", "include", "exclude"):
            if key in request.data:
                data[key] = request.data.getlist(key)
        return data
    return dict(request.data)


class SourceViewSet(TenantContextMixin, viewsets.ModelViewSet):
    serializer_class = SourceSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        if self.action in ("approve", "unapprove"):
            return [permissions.IsAuthenticated(), perm("knowledge.approve")()]
        return _perms(self)

    def get_queryset(self):
        qs = Source.objects.filter(company=self.request.company).prefetch_related("employees")
        for key in ("type", "approval", "status"):
            if self.request.query_params.get(key):
                qs = qs.filter(**{key: self.request.query_params[key]})
        return qs

    def create(self, request, *args, **kwargs):
        source = _errors(
            kb.create_source, request.company, _data(request), request.FILES.get("file"), request.user, request._request
        )
        return Response(SourceSerializer(source).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        source = _errors(kb.update_source, self.get_object(), _data(request), request.user, request._request)
        return Response(SourceSerializer(source).data)

    def destroy(self, request, *args, **kwargs):
        kb.delete_source(self.get_object(), request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return Response(
            SourceSerializer(_errors(kb.approve, self.get_object(), True, request.user, request._request)).data
        )

    @action(detail=True, methods=["post"])
    def unapprove(self, request, pk=None):
        return Response(
            SourceSerializer(_errors(kb.approve, self.get_object(), False, request.user, request._request)).data
        )

    @action(detail=True, methods=["post"])
    def reprocess(self, request, pk=None):
        return Response(SourceSerializer(_errors(kb.reprocess, self.get_object(), request._request)).data)


class FAQViewSet(TenantContextMixin, viewsets.ModelViewSet):
    serializer_class = FAQSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_permissions(self):
        if self.action == "approve":
            return [permissions.IsAuthenticated(), perm("knowledge.approve")()]
        return _perms(self)

    def get_queryset(self):
        qs = FAQ.objects.filter(company=self.request.company)
        if self.request.query_params.get("source"):
            qs = qs.filter(source_id=self.request.query_params["source"])
        return qs

    def _source(self, pk):
        return get_object_or_404(Source, pk=pk, company=self.request.company, type=Source.FAQ)

    def create(self, request, *args, **kwargs):
        faq = _errors(kb.save_faq, self._source(request.data.get("source")), request.data, None, request._request)
        return Response(FAQSerializer(faq).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        faq = self.get_object()
        data = {"question": faq.question, "answer": faq.answer, **request.data}
        data.pop("approved", None)
        faq = _errors(kb.save_faq, faq.source, data, faq, request._request)
        return Response(FAQSerializer(faq).data)

    def destroy(self, request, *args, **kwargs):
        kb.delete_faq(self.get_object(), request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        approved = str(request.data.get("approved", "true")).lower() not in ("false", "0")
        return Response(FAQSerializer(kb.approve_faq(self.get_object(), approved, request._request)).data)

    @action(detail=False, methods=["post"], url_path="import")
    def bulk_import(self, request):
        if not request.FILES.get("file"):
            raise ValidationError({"file": "Required."})
        count = _errors(
            kb.import_faqs, self._source(request.data.get("source")), request.FILES["file"], request._request
        )
        return Response({"imported": count})


class TestQueryView(TenantContextMixin, APIView):
    def get_permissions(self):
        return [permissions.IsAuthenticated(), perm("knowledge.view")()]

    def post(self, request):
        employee = None
        if request.data.get("employee"):
            employee = get_object_or_404(AIEmployee, pk=request.data["employee"], company=request.company)
        return Response(_errors(kb.test_query, request.company, request.data.get("question"), employee, request.user))


class UnansweredViewSet(TenantContextMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    serializer_class = UnansweredSerializer

    def get_permissions(self):
        return _perms(self, write="knowledge.manage")

    def get_queryset(self):
        qs = UnansweredQuestion.objects.filter(company=self.request.company)
        return qs.filter(status=self.request.query_params.get("status") or UnansweredQuestion.OPEN)

    @action(detail=True, methods=["post"])
    def resolve(self, request, pk=None):
        item = get_object_or_404(UnansweredQuestion, pk=pk, company=request.company)
        return Response(UnansweredSerializer(kb.resolve_unanswered(item, request._request)).data)
