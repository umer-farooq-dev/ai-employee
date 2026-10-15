"""REST API for catalogues (CAT-01, CAT-02, CAT-04 … CAT-08): /api/v1/catalog/…"""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog import services as catalog
from apps.catalog.models import CatalogCollection, CatalogImport, CatalogItem, CatalogMedia
from apps.core.money import format_inr, format_inr_short
from apps.core.storage import signed_url

from .base import TenantContextMixin, perm
from .views_templates import CatalogTypeSerializer, FieldSerializer


def _errors(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except DjangoValidationError as exc:
        raise ValidationError(exc.messages) from None


class _CatalogPerm(TenantContextMixin):
    def get_permissions(self):
        key = "catalog.view" if self.request.method in permissions.SAFE_METHODS else "catalog.manage"
        return [permissions.IsAuthenticated(), perm(key)()]


class MediaSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = CatalogMedia
        fields = ["id", "kind", "file_name", "url", "sort_order"]

    def get_url(self, obj) -> str:
        return signed_url(obj.file_key)


class ItemSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="catalog_type.key", read_only=True)
    price = serializers.SerializerMethodField()
    media = MediaSerializer(many=True, read_only=True)

    class Meta:
        model = CatalogItem
        fields = [
            "id",
            "type",
            "title",
            "status",
            "price_paise",
            "price",
            "attributes",
            "media",
            "created_at",
            "updated_at",
        ]

    def get_price(self, obj) -> dict | None:
        if obj.price_paise is None:
            return None
        return {"formatted": format_inr(obj.price_paise), "short": format_inr_short(obj.price_paise)}


class CatalogTypesView(_CatalogPerm, APIView):
    @extend_schema(responses=dict)
    def get(self, request):
        return Response(
            [
                {
                    **CatalogTypeSerializer(t).data,
                    "fields": FieldSerializer(catalog.fields(request.company, t), many=True).data,
                }
                for t in catalog.types(request.company)
            ]
        )


class CatalogItemViewSet(_CatalogPerm, viewsets.ModelViewSet):
    """?type=<key> plus the item list filters (q, status, sort, f_<field>, f_<field>_min / _max)."""

    serializer_class = ItemSerializer
    parser_classes = [JSONParser, MultiPartParser]

    def get_queryset(self):
        if self.action == "list":
            ctype = _errors(catalog.get_type, self.request.company, self.request.query_params.get("type", ""))
            return catalog.filter_items(self.request.company, ctype, self.request.query_params)
        return CatalogItem.objects.select_related("catalog_type").prefetch_related("media")

    def create(self, request):
        ctype = _errors(catalog.get_type, request.company, request.data.get("type", ""))
        item = _errors(
            catalog.create_item,
            request.company,
            ctype,
            request.data.get("attributes") or {},
            request.data.get("status") or CatalogItem.ACTIVE,
            request=request._request,
        )
        return Response(ItemSerializer(item).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        item = _errors(
            catalog.update_item,
            self.get_object(),
            request.data.get("attributes") or {},
            request.data.get("status"),
            request=request._request,
        )
        return Response(ItemSerializer(item).data)

    update = partial_update

    def destroy(self, request, pk=None):
        catalog.delete_item(self.get_object(), request=request._request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=dict, responses=dict)
    @action(detail=False, methods=["post"])
    def bulk(self, request):
        """CAT-07: {"ids": [...], "field": "status" | <field key> | "delete", "value": ...}."""
        items = CatalogItem.objects.filter(pk__in=request.data.get("ids") or [])
        count = _errors(
            catalog.bulk_edit,
            request.company,
            items,
            request.data.get("field"),
            request.data.get("value"),
            request._request,
        )
        return Response({"updated": count})

    @extend_schema(request=dict, responses=MediaSerializer)
    @action(detail=True, methods=["post", "delete"])
    def media(self, request, pk=None):
        item = self.get_object()
        if request.method == "DELETE":
            catalog.remove_media(
                get_object_or_404(CatalogMedia, pk=request.query_params.get("id"), item=item), request=request._request
            )
            return Response(status=status.HTTP_204_NO_CONTENT)
        if not request.FILES.get("file"):
            raise ValidationError({"file": "Required."})
        media = _errors(
            catalog.add_media, item, request.FILES["file"], request.data.get("kind", "photo"), request._request
        )
        return Response(MediaSerializer(media).data, status=status.HTTP_201_CREATED)


class CollectionSerializer(serializers.ModelSerializer):
    type = serializers.CharField(source="catalog_type.key", read_only=True)
    item_ids = serializers.SerializerMethodField()

    class Meta:
        model = CatalogCollection
        fields = ["id", "type", "name", "description", "mode", "filter", "item_ids"]

    def get_item_ids(self, obj) -> list[str]:
        return [str(i.pk) for i in catalog.collection_items(obj)]


class CollectionViewSet(_CatalogPerm, viewsets.ModelViewSet):
    """CAT-04. Create / update with {"type", "name", "description", "mode", "filter", "items": [ids]}."""

    serializer_class = CollectionSerializer
    pagination_class = None

    def get_queryset(self):
        qs = CatalogCollection.objects.select_related("catalog_type")
        if self.request.query_params.get("type"):
            qs = qs.filter(catalog_type__key=self.request.query_params["type"])
        return qs

    def _save(self, request, collection=None):
        ctype = (
            collection.catalog_type
            if collection
            else _errors(catalog.get_type, request.company, request.data.get("type", ""))
        )
        collection = _errors(
            catalog.save_collection, request.company, ctype, request.data, collection, request._request
        )
        if collection.mode == CatalogCollection.MANUAL and "items" in request.data:
            catalog.set_collection_items(collection, request.data.get("items") or [], request=request._request)
        return collection

    def create(self, request):
        return Response(CollectionSerializer(self._save(request)).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        return Response(CollectionSerializer(self._save(request, self.get_object())).data)

    update = partial_update


class CatalogImportView(TenantContextMixin, APIView):
    """POST multipart {type, file} → mapping; POST {mapping} to /<id>/ runs the import."""

    permission_classes = [permissions.IsAuthenticated, perm("catalog.manage")]
    parser_classes = [MultiPartParser, JSONParser]

    def _data(self, imp):
        return {
            "id": imp.id,
            "status": imp.status,
            "headers": imp.headers,
            "mapping": imp.mapping,
            "total": imp.total,
            "created": imp.created,
            "failed": imp.failed,
            "errors": imp.errors[:200],
        }

    @extend_schema(request=dict, responses=dict)
    def post(self, request, pk=None):
        if pk is None:
            ctype = _errors(catalog.get_type, request.company, request.data.get("type", ""))
            if not request.FILES.get("file"):
                raise ValidationError({"file": "Required."})
            imp = _errors(catalog.start_import, request.company, ctype, request.FILES["file"], request._request)
            return Response(self._data(imp), status=status.HTTP_201_CREATED)
        imp = get_object_or_404(CatalogImport, pk=pk)
        if imp.status != "pending":
            raise ValidationError("This import has already run.")
        return Response(
            self._data(_errors(catalog.run_import, imp, request.data.get("mapping") or {}, request._request))
        )
