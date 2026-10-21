from __future__ import annotations

import hashlib

from django.utils import timezone

from bookmarks.utils import normalize_url
from research.models import ResearchTask, Source


def _web_key(url: str) -> str:
    normalized = normalize_url(url) or url
    return "web:" + hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def get_or_create_bookmark_source(task: ResearchTask, bookmark) -> Source:
    key = f"bookmark:{bookmark.id}"
    source, _ = Source.objects.get_or_create(
        task=task,
        source_key=key,
        defaults={
            "bookmark": bookmark,
            "source_type": Source.TYPE_BOOKMARK,
            "url": bookmark.url,
            "url_normalized": bookmark.url_normalized,
            "title": bookmark.resolved_title,
        },
    )
    changed = False
    if source.title != bookmark.resolved_title:
        source.title = bookmark.resolved_title
        changed = True
    if source.url != bookmark.url:
        source.url = bookmark.url
        source.url_normalized = bookmark.url_normalized
        changed = True
    content = getattr(bookmark, "content", None)
    if content and content.status == "ready" and content.text and not source.content_text:
        source.content_text = content.text
        source.content_hash = content.content_hash
        source.fetch_status = Source.FETCH_READY
        source.fetched_at = content.fetched_at or timezone.now()
        changed = True
    if changed:
        source.save()
    return source


def get_or_create_web_source(
    task: ResearchTask,
    url: str,
    title: str = "",
    snippet: str = "",
    sub_question=None,
) -> Source:
    key = _web_key(url)
    source = Source.objects.filter(task=task, source_key=key).first()
    if source is None:
        source = Source.objects.create(
            task=task,
            source_key=key,
            source_type=Source.TYPE_WEB,
            url=url,
            url_normalized=normalize_url(url),
            title=title[:512],
            snippet=snippet[:2000],
            sub_question=sub_question,
        )
        return source

    changed = False
    if title and source.title != title[:512]:
        source.title = title[:512]
        changed = True
    if snippet and source.snippet != snippet[:2000]:
        source.snippet = snippet[:2000]
        changed = True
    if sub_question and not source.sub_question_id:
        source.sub_question = sub_question
        changed = True
    if changed:
        source.save()
    return source
