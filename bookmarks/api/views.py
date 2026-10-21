from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from bookmarks.api.serializers import (
    BookmarkListSerializer,
    BookmarkSerializer,
    DocumentContentSerializer,
)
from bookmarks.queries import query_bookmarks
from bookmarks.services.reader import get_or_fetch_content
from bookmarks.services.tags import parse_tag_names


class BookmarkViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    def get_queryset(self):
        archived = self.request.query_params.get("archived", "0") in {"1", "true", "yes"}
        return query_bookmarks(
            self.request.user,
            q=self.request.query_params.get("q", ""),
            tag_names=parse_tag_names(self.request.query_params.get("tags", "")),
            archived=archived,
        )

    def get_serializer_class(self):
        if self.action == "list":
            return BookmarkListSerializer
        return BookmarkSerializer

    @action(detail=True, methods=["get", "post"], url_path="content")
    def content(self, request, pk=None):
        bookmark = self.get_object()
        refresh = request.query_params.get("refresh") in {"1", "true", "yes"}
        content = get_or_fetch_content(bookmark, refresh=refresh)
        return Response(DocumentContentSerializer(content).data, status=status.HTTP_200_OK)
