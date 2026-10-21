from django.utils import timezone

from bookmarks.models import Bookmark
from bookmarks.services.tags import get_or_create_tags, parse_tag_names


def _apply_tags(bookmark: Bookmark, tag_names, replace: bool = False) -> None:
    tags = get_or_create_tags(bookmark.owner, tag_names)
    if replace:
        bookmark.tags.set(tags)
    else:
        bookmark.tags.add(*tags)


def create_bookmark(
    owner,
    url: str,
    title: str = "",
    description: str = "",
    notes: str = "",
    tag_names=None,
    unread: bool = False,
) -> tuple[Bookmark, bool]:
    """Create a bookmark, merging into an existing one with the same URL.

    Returns (bookmark, created).
    """
    existing = Bookmark.query_existing(owner, url).first()
    if existing:
        if title:
            existing.title = title
        if description:
            existing.description = description
        if notes:
            existing.notes = notes
        if unread:
            existing.unread = True
        existing.date_modified = timezone.now()
        existing.save()
        _apply_tags(existing, tag_names or [])
        return existing, False

    bookmark = Bookmark(
        owner=owner,
        url=url,
        title=title or "",
        description=description or "",
        notes=notes or "",
        unread=unread,
        date_added=timezone.now(),
        date_modified=timezone.now(),
    )
    bookmark.save()
    _apply_tags(bookmark, tag_names or [])
    return bookmark, True


def update_bookmark(
    bookmark: Bookmark,
    url: str | None = None,
    title: str | None = None,
    description: str | None = None,
    notes: str | None = None,
    tag_names=None,
    unread: bool | None = None,
    is_archived: bool | None = None,
) -> Bookmark:
    if url is not None:
        bookmark.url = url
    if title is not None:
        bookmark.title = title
    if description is not None:
        bookmark.description = description
    if notes is not None:
        bookmark.notes = notes
    if unread is not None:
        bookmark.unread = unread
    if is_archived is not None:
        bookmark.is_archived = is_archived

    if tag_names is not None:
        _apply_tags(bookmark, tag_names, replace=True)

    bookmark.date_modified = timezone.now()
    bookmark.save()
    return bookmark


def delete_bookmark(bookmark: Bookmark) -> None:
    bookmark.delete()


def all_tag_names(owner) -> list[str]:
    from bookmarks.models import Tag

    return sorted(Tag.objects.filter(owner=owner).values_list("name", flat=True))


def normalize_tag_input(raw) -> list[str]:
    return parse_tag_names(raw)
