from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from bookmarks.models import Bookmark
from bookmarks.queries import query_bookmarks
from bookmarks.services import bookmarks as bookmark_service
from bookmarks.services.tags import parse_tag_names
from bookmarks.utils import normalize_url

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return get_user_model().objects.create_user(username="owner", password="x")


@pytest.fixture
def other():
    return get_user_model().objects.create_user(username="other", password="x")


def test_normalize_url_sorts_query_and_trims_slash():
    left = normalize_url("HTTPS://Example.COM/a/?b=2&a=1")
    right = normalize_url("https://example.com/a?a=1&b=2")
    assert left == right


def test_normalize_url_keeps_fragment():
    assert normalize_url("https://example.com/a#s1") != normalize_url(
        "https://example.com/a#s2"
    )


def test_parse_tag_names_handles_chinese_comma():
    assert parse_tag_names("Redis，架构, redis,, 数据库") == [
        "Redis",
        "架构",
        "数据库",
    ]


def test_create_bookmark_merges_same_url(owner):
    first, created = bookmark_service.create_bookmark(
        owner=owner,
        url="https://example.com/post/",
        title="标题",
        tag_names=["redis"],
    )
    second, created_again = bookmark_service.create_bookmark(
        owner=owner,
        url="https://example.com/post",
        description="新描述",
        tag_names=["缓存"],
    )

    assert created is True
    assert created_again is False
    assert first.pk == second.pk
    assert second.title == "标题"
    assert second.description == "新描述"
    assert set(second.tag_names) == {"redis", "缓存"}


def test_query_bookmarks_filters_by_tag_and_archive(owner):
    bookmark_service.create_bookmark(
        owner=owner, url="https://a.test/1", title="Redis 持久化", tag_names=["redis"]
    )
    bookmark_service.create_bookmark(
        owner=owner, url="https://a.test/2", title="Django ORM", tag_names=["django"]
    )
    archived, _ = bookmark_service.create_bookmark(
        owner=owner, url="https://a.test/3", title="Redis 旧文", tag_names=["redis"]
    )
    bookmark_service.update_bookmark(archived, is_archived=True)

    active = list(query_bookmarks(owner, q="Redis"))
    assert [item.pk for item in active] == [
        Bookmark.objects.get(url="https://a.test/1").pk
    ]

    tagged = list(query_bookmarks(owner, tag_names=["redis"]))
    assert len(tagged) == 1

    archived_items = list(query_bookmarks(owner, archived=True))
    assert [item.pk for item in archived_items] == [archived.pk]


def test_api_requires_token_and_scopes_owner(owner, other):
    bookmark_service.create_bookmark(owner=owner, url="https://a.test/1", title="A")
    bookmark_service.create_bookmark(owner=other, url="https://b.test/1", title="B")

    client = APIClient()
    assert client.get("/api/bookmarks/").status_code in {401, 403}

    token = Token.objects.create(user=owner)
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    response = client.get("/api/bookmarks/")

    assert response.status_code == 200
    titles = [item["title"] for item in response.json()["results"]]
    assert titles == ["A"]


def test_api_create_and_patch_bookmark(owner):
    token = Token.objects.create(user=owner)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    response = client.post(
        "/api/bookmarks/",
        {"url": "https://a.test/1", "title": "A", "tag_names": ["x"]},
        format="json",
    )
    assert response.status_code == 201
    bookmark_id = response.json()["id"]

    response = client.patch(
        f"/api/bookmarks/{bookmark_id}/", {"title": "A2"}, format="json"
    )
    assert response.status_code == 200
    assert response.json()["title"] == "A2"
