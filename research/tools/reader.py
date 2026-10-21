from __future__ import annotations

import hashlib

from django.utils import timezone

from bookmarks.services.reader import FetchError, extract_text, get_or_fetch_content, safe_fetch
from research.models import Source
from research.tools.base import ToolContext, ToolError, ToolResult

MAX_STORED_CHARS = 200_000


def _load_source_text(ctx: ToolContext, source: Source) -> str:
    if source.content_text:
        return source.content_text

    if source.source_type == Source.TYPE_BOOKMARK and source.bookmark_id:
        content = get_or_fetch_content(source.bookmark)
        if content.status != "ready" or not content.text:
            source.fetch_status = Source.FETCH_FAILED
            source.save(update_fields=["fetch_status"])
            raise ToolError(
                "bookmark_fetch_failed",
                f"书签正文抓取失败：{content.error or '正文为空'}",
                "可以调用 web_search 找同一主题的其他来源，或换一个书签。",
            )
        text = content.text
        source.content_hash = content.content_hash
    else:
        if ctx.offline:
            raise ToolError(
                "offline_mode",
                "离线评测模式不能抓取网页",
                "请只使用本地书签来源。",
            )
        try:
            final_url, html, status = safe_fetch(source.url)
        except FetchError as exc:
            source.fetch_status = Source.FETCH_FAILED
            source.save(update_fields=["fetch_status"])
            raise ToolError(
                "web_fetch_failed",
                f"网页抓取失败：{exc}",
                "换一个来源，或改写检索词后再试。",
            ) from exc
        text = extract_text(html)
        if not text:
            source.fetch_status = Source.FETCH_FAILED
            source.save(update_fields=["fetch_status"])
            raise ToolError(
                "empty_document",
                "抓取成功但正文为空",
                "换一个来源，或改用书签库。",
            )
        source.http_status = status
        source.content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    source.content_text = text[:MAX_STORED_CHARS]
    source.fetch_status = Source.FETCH_READY
    source.fetched_at = timezone.now()
    source.save(
        update_fields=[
            "content_text",
            "content_hash",
            "fetch_status",
            "http_status",
            "fetched_at",
        ]
    )
    return source.content_text


def read_document(
    ctx: ToolContext, source_id: int, offset: int = 0, max_chars: int = 6000
) -> ToolResult:
    source = Source.objects.filter(task=ctx.task, pk=source_id).first()
    if source is None:
        raise ToolError("source_not_found", f"来源 {source_id} 不属于当前任务")

    text = _load_source_text(ctx, source)
    total = len(text)
    if offset >= total:
        return ToolResult(
            ok=False,
            error_code="offset_out_of_range",
            message=f"offset {offset} 超出正文长度 {total}",
            hint="从 0 开始读取，或根据 next_offset 继续。",
            data={"total_chars": total},
        )

    chunk = text[offset : offset + max_chars]
    next_offset = offset + len(chunk)
    return ToolResult(
        ok=True,
        data={
            "source_id": source.id,
            "title": source.title,
            "url": source.url,
            "offset": offset,
            "next_offset": next_offset if next_offset < total else None,
            "total_chars": total,
            "text": chunk,
        },
        message=f"读取 {len(chunk)} 字，共 {total} 字",
        hint="提取证据时 quote 必须是这段正文的连续片段。",
    )
