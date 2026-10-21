from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

from bookmarks.utils import normalize_url


class Tag(models.Model):
    name = models.CharField(max_length=64)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tags"
    )
    date_added = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "owner", name="uniq_tag_owner_lower_name"
            )
        ]
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Bookmark(models.Model):
    url = models.CharField(max_length=2048)
    url_normalized = models.CharField(max_length=2048, blank=True, db_index=True)
    title = models.CharField(max_length=512, blank=True)
    description = models.TextField(blank=True)
    notes = models.TextField(blank=True)
    unread = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    date_added = models.DateTimeField(default=timezone.now)
    date_modified = models.DateTimeField(default=timezone.now)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="bookmarks"
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="bookmarks")

    class Meta:
        ordering = ["-date_added"]
        indexes = [
            models.Index(
                fields=["owner", "is_archived", "-date_added"],
                name="bm_owner_arch_added_idx",
            ),
            models.Index(
                fields=["owner", "url_normalized"], name="bm_owner_normurl_idx"
            ),
        ]

    def save(self, *args, **kwargs):
        self.url_normalized = normalize_url(self.url)
        super().save(*args, **kwargs)

    @classmethod
    def query_existing(cls, owner, url: str):
        normalized = normalize_url(url)
        return cls.objects.filter(owner=owner).filter(
            Q(url_normalized=normalized) | Q(url_normalized="", url=url)
        )

    @property
    def resolved_title(self) -> str:
        return self.title or self.url

    @property
    def tag_names(self) -> list[str]:
        return sorted(self.tags.values_list("name", flat=True))

    def __str__(self) -> str:
        return self.resolved_title


class DocumentContent(models.Model):
    STATUS_PENDING = "pending"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "待抓取"),
        (STATUS_READY, "已就绪"),
        (STATUS_FAILED, "失败"),
    ]

    bookmark = models.OneToOneField(
        Bookmark, on_delete=models.CASCADE, related_name="content"
    )
    text = models.TextField(blank=True)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    error = models.TextField(blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    fetched_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"content:{self.bookmark_id}"
