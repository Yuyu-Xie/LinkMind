"""Fetch and cache readable text for bookmarks.

All outbound fetches go through safe_fetch, which rejects private network
addresses and limits response size to reduce SSRF exposure.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup
from django.utils import timezone

from bookmarks.models import Bookmark, DocumentContent

logger = logging.getLogger("bookmarks")

MAX_BYTES = 2 * 1024 * 1024
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 20
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 LinkMind/0.1"
)
ALLOWED_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "text/plain",
    "application/xml",
    "text/xml",
}


class FetchError(Exception):
    pass


def _assert_public_host(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise FetchError(f"只支持 http/https: {parsed.scheme}")
    host = parsed.hostname
    if not host:
        raise FetchError("URL 缺少主机名")

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise FetchError(f"域名解析失败: {host}") from exc

    for info in infos:
        address = info[4][0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise FetchError(f"拒绝访问内网地址: {address}")


def safe_fetch(url: str) -> tuple[str, str, int]:
    """Fetch a URL, following redirects with per-hop validation.

    Returns (final_url, html, status_code).
    """
    current = url
    with httpx.Client(
        timeout=TIMEOUT_SECONDS,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
        follow_redirects=False,
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            _assert_public_host(current)
            try:
                with client.stream("GET", current) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise FetchError("重定向缺少 Location")
                        current = urljoin(current, location)
                        continue

                    if response.status_code >= 400:
                        raise FetchError(f"HTTP {response.status_code}")

                    content_type = response.headers.get("content-type", "").split(";")[0]
                    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
                        raise FetchError(f"不支持的内容类型: {content_type}")

                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > MAX_BYTES:
                            raise FetchError("响应超过 2MB 限制")
                        chunks.append(chunk)

                    body = b"".join(chunks)
                    encoding = response.encoding or "utf-8"
                    try:
                        text = body.decode(encoding, errors="replace")
                    except LookupError:
                        text = body.decode("utf-8", errors="replace")
                    return str(response.url), text, response.status_code
            except httpx.HTTPError as exc:
                raise FetchError(f"请求失败: {exc}") from exc

    raise FetchError("重定向次数过多")


def extract_text(html: str) -> str:
    if not html.strip():
        return ""
    try:
        extracted = trafilatura.extract(
            html,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
            output_format="txt",
        )
    except Exception:  # trafilatura can raise on malformed documents
        extracted = None
    if extracted and extracted.strip():
        return _normalize_text(extracted)

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return _normalize_text(soup.get_text("\n"))


def _normalize_text(text: str) -> str:
    lines = [line.strip() for line in text.replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line)


def get_or_fetch_content(
    bookmark: Bookmark, refresh: bool = False
) -> DocumentContent:
    content = DocumentContent.objects.filter(bookmark=bookmark).first()
    if content is None:
        content = DocumentContent(bookmark=bookmark)

    if content.status == DocumentContent.STATUS_READY and not refresh and content.text:
        return content

    content.status = DocumentContent.STATUS_PENDING
    content.error = ""
    content.save()

    try:
        final_url, html, status = safe_fetch(bookmark.url)
        text = extract_text(html)
        if not text:
            raise FetchError("正文为空")
        content.text = text
        content.content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        content.status = DocumentContent.STATUS_READY
        content.fetched_at = timezone.now()
        content.save()
        logger.info("fetched bookmark %s (%s, %s chars)", bookmark.id, status, len(text))
    except Exception as exc:
        content.status = DocumentContent.STATUS_FAILED
        content.error = str(exc)[:1000]
        content.fetched_at = timezone.now()
        content.save()
        logger.warning("fetch failed for bookmark %s: %s", bookmark.id, exc)

    return content
