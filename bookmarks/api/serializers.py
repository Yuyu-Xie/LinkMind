from rest_framework import serializers

from bookmarks.models import Bookmark, DocumentContent
from bookmarks.services import bookmarks as bookmark_service


class BookmarkListSerializer(serializers.ModelSerializer):
    tag_names = serializers.SerializerMethodField()
    content_status = serializers.SerializerMethodField()

    class Meta:
        model = Bookmark
        fields = [
            "id",
            "url",
            "title",
            "description",
            "tag_names",
            "unread",
            "is_archived",
            "date_added",
            "date_modified",
            "content_status",
        ]

    def get_tag_names(self, obj) -> list[str]:
        return sorted(tag.name for tag in obj.tags.all())

    def get_content_status(self, obj) -> str | None:
        content = getattr(obj, "content", None)
        return content.status if content else None


class BookmarkSerializer(serializers.ModelSerializer):
    tag_names = serializers.ListField(
        child=serializers.CharField(max_length=64), required=False, default=list
    )

    class Meta:
        model = Bookmark
        fields = [
            "id",
            "url",
            "title",
            "description",
            "notes",
            "tag_names",
            "unread",
            "is_archived",
            "date_added",
            "date_modified",
        ]
        read_only_fields = ["id", "date_added", "date_modified"]

    def create(self, validated_data):
        tag_names = validated_data.pop("tag_names", [])
        bookmark, _ = bookmark_service.create_bookmark(
            owner=self.context["request"].user,
            tag_names=tag_names,
            **validated_data,
        )
        return bookmark

    def update(self, instance, validated_data):
        tag_names = validated_data.pop("tag_names", None)
        return bookmark_service.update_bookmark(
            instance, tag_names=tag_names, **validated_data
        )


class DocumentContentSerializer(serializers.ModelSerializer):
    class Meta:
        model = DocumentContent
        fields = ["status", "text", "error", "content_hash", "fetched_at"]
