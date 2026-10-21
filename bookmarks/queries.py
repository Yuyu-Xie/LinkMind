from django.db.models import Q, QuerySet

from bookmarks.models import Bookmark


def _search_q(term: str) -> Q:
    return (
        Q(title__icontains=term)
        | Q(description__icontains=term)
        | Q(notes__icontains=term)
        | Q(url__icontains=term)
    )


def query_bookmarks(
    owner,
    q: str = "",
    tag_names: list[str] | None = None,
    archived: bool = False,
) -> QuerySet[Bookmark]:
    queryset = Bookmark.objects.filter(owner=owner, is_archived=archived)

    for term in (q or "").split():
        queryset = queryset.filter(_search_q(term))

    for tag_name in tag_names or []:
        queryset = queryset.filter(tags__name__iexact=tag_name)

    if tag_names:
        queryset = queryset.distinct()

    return (
        queryset.select_related("content")
        .prefetch_related("tags")
        .order_by("-date_added")
    )


def query_tags(owner):
    from bookmarks.models import Tag

    return Tag.objects.filter(owner=owner).order_by("name")
