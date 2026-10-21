from research.services.sources import get_or_create_web_source
from research.services.websearch import SearchProviderError, web_search
from research.tools.base import ToolContext, ToolResult


def search_web(ctx: ToolContext, query: str, limit: int = 5) -> ToolResult:
    if ctx.offline:
        return ToolResult(
            ok=False,
            error_code="offline_mode",
            message="当前任务处于离线评测模式，网页检索不可用",
            hint="请只使用 search_bookmarks 检索本地语料。",
        )

    try:
        results = web_search(query, limit)
    except SearchProviderError as exc:
        return ToolResult(
            ok=False,
            error_code="search_failed",
            message=str(exc),
            hint="换一个关键词重试，或改用 search_bookmarks。",
        )

    items = []
    for item in results:
        source = get_or_create_web_source(
            ctx.task, item.url, title=item.title, snippet=item.snippet
        )
        items.append(
            {
                "source_id": source.id,
                "title": source.title,
                "url": source.url,
                "snippet": item.snippet[:300],
            }
        )

    if not items:
        return ToolResult(
            ok=True,
            data={"results": [], "count": 0},
            message="网页检索没有结果",
            hint="改写关键词，或改用 search_bookmarks。",
        )

    return ToolResult(
        ok=True,
        data={"results": items, "count": len(items)},
        message=f"找到 {len(items)} 条网页结果",
        hint="需要正文时调用 read_document(source_id)。",
    )
