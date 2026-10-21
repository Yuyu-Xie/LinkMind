from bookmarks.queries import query_bookmarks
from research.services.sources import get_or_create_bookmark_source
from research.tools.base import ToolContext, ToolResult


def search_bookmarks(
    ctx: ToolContext, query: str, tags: list[str] | None = None, limit: int = 5
) -> ToolResult:
    queryset = query_bookmarks(
        ctx.task.owner, q=query, tag_names=tags or [], archived=False
    )[:limit]

    results = []
    for bookmark in queryset:
        source = get_or_create_bookmark_source(ctx.task, bookmark)
        snippet = bookmark.description or bookmark.notes
        if not snippet and source.content_text:
            snippet = source.content_text[:300]
        results.append(
            {
                "source_id": source.id,
                "bookmark_id": bookmark.id,
                "title": bookmark.resolved_title,
                "url": bookmark.url,
                "snippet": snippet[:300],
                "tags": bookmark.tag_names,
                "has_content": source.is_readable,
            }
        )

    if not results:
        return ToolResult(
            ok=True,
            data={"results": [], "count": 0},
            message="没有匹配的书签",
            hint="改写关键词、减少标签限制，或调用 web_search 检索互联网。",
        )

    return ToolResult(
        ok=True,
        data={"results": results, "count": len(results)},
        message=f"找到 {len(results)} 条书签",
        hint="需要正文时调用 read_document(source_id)。",
    )
