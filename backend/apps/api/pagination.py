from rest_framework import pagination


class CursorPagination(pagination.CursorPagination):
    """API-06: cursor pagination for mobile; clients may ask for up to max_page_size items."""

    ordering = "-created_at"
    page_size_query_param = "page_size"
    max_page_size = 100


class UserPagination(CursorPagination):
    ordering = "-date_joined"
