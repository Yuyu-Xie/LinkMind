from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

import httpx
from bs4 import BeautifulSoup
from django.conf import settings

logger = logging.getLogger("research")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

_last_request_at = 0.0


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""


class SearchProviderError(Exception):
    pass


def _throttle(seconds: float = 1.0) -> None:
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < seconds:
        time.sleep(seconds - elapsed)
    _last_request_at = time.monotonic()


def _decode_bing_url(url: str) -> str:
    if "bing.com/ck/a" not in url:
        return url
    try:
        query = parse_qs(urlparse(url).query)
        encoded = (query.get("u") or [""])[0]
        if encoded.startswith("a1"):
            encoded = encoded[2:]
        encoded += "=" * (-len(encoded) % 4)
        return base64.urlsafe_b64decode(encoded).decode("utf-8", errors="replace")
    except Exception:
        return url


class BingProvider:
    name = "bing"

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        _throttle()
        try:
            response = httpx.get(
                "https://cn.bing.com/search",
                params={"q": query, "count": max(limit, 10), "setlang": "zh-Hans"},
                headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"},
                timeout=15,
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SearchProviderError(f"Bing 请求失败: {exc}") from exc

        soup = BeautifulSoup(response.text, "lxml")
        results: list[SearchResult] = []
        for item in soup.select("li.b_algo"):
            link = item.select_one("h2 a")
            if not link or not link.get("href"):
                continue
            caption = item.select_one(".b_caption p") or item.select_one(".b_algoSlug")
            results.append(
                SearchResult(
                    title=link.get_text(" ", strip=True),
                    url=_decode_bing_url(link["href"]),
                    snippet=caption.get_text(" ", strip=True) if caption else "",
                )
            )
            if len(results) >= limit:
                break
        return results


class BaiduProvider:
    name = "baidu"

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        _throttle()
        try:
            response = httpx.get(
                "https://www.baidu.com/s",
                params={"wd": query},
                headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"},
                timeout=15,
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SearchProviderError(f"Baidu 请求失败: {exc}") from exc

        soup = BeautifulSoup(response.text, "lxml")
        results: list[SearchResult] = []
        for item in soup.select("div.result, div.c-container"):
            link = item.select_one("h3 a")
            if not link or not link.get("href"):
                continue
            snippet = item.select_one(".c-abstract") or item.select_one(".content-right_8Zs40")
            results.append(
                SearchResult(
                    title=link.get_text(" ", strip=True),
                    url=unquote(link["href"]),
                    snippet=snippet.get_text(" ", strip=True) if snippet else "",
                )
            )
            if len(results) >= limit:
                break
        return results


class TavilyProvider:
    name = "tavily"

    def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        if not settings.TAVILY_API_KEY:
            raise SearchProviderError("未配置 TAVILY_API_KEY")
        try:
            response = httpx.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": settings.TAVILY_API_KEY,
                    "query": query,
                    "max_results": limit,
                    "search_depth": "basic",
                },
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise SearchProviderError(f"Tavily 请求失败: {exc}") from exc

        return [
            SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("content", "")[:500],
            )
            for item in payload.get("results", [])
            if item.get("url")
        ]


_PROVIDERS = {
    "bing": BingProvider,
    "baidu": BaiduProvider,
    "tavily": TavilyProvider,
}


def get_provider(name: str | None = None):
    key = (name or settings.WEB_SEARCH_PROVIDER or "bing").lower()
    return _PROVIDERS.get(key, BingProvider)()


def web_search(query: str, limit: int = 5) -> list[SearchResult]:
    provider = get_provider()
    try:
        results = provider.search(query, limit)
    except SearchProviderError:
        if provider.name != "bing":
            raise
        logger.warning("Bing 检索失败，回退 Baidu")
        results = BaiduProvider().search(query, limit)
    return [item for item in results if item.url.startswith(("http://", "https://"))]
