from django.contrib import admin

from bookmarks.models import Bookmark, DocumentContent, Tag


@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "url", "owner", "is_archived", "date_added")
    list_filter = ("is_archived", "unread")
    search_fields = ("title", "url", "description")
    raw_id_fields = ("owner",)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "owner")
    search_fields = ("name",)


@admin.register(DocumentContent)
class DocumentContentAdmin(admin.ModelAdmin):
    list_display = ("bookmark", "status", "fetched_at")
    list_filter = ("status",)
