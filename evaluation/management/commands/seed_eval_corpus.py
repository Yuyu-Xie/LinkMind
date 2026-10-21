from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from bookmarks.models import Bookmark, DocumentContent
from bookmarks.services import bookmarks as bookmark_service
from evaluation.services.dataset import load_corpus


class Command(BaseCommand):
    help = "把 evaluation/data/corpus 导入指定用户的本地书签，作为离线评测语料"

    def add_arguments(self, parser):
        parser.add_argument("--user", default="demo")
        parser.add_argument(
            "--fresh", action="store_true", help="先删除该用户带 eval-corpus 标签的书签"
        )

    @transaction.atomic
    def handle(self, *args, **options):
        user_model = get_user_model()
        owner = user_model.objects.filter(username=options["user"]).first()
        if owner is None:
            raise CommandError(f"用户 {options['user']} 不存在，先运行 seed_demo")

        if options["fresh"]:
            deleted, _ = Bookmark.objects.filter(
                owner=owner, tags__name="eval-corpus"
            ).delete()
            self.stdout.write(f"已删除旧评测书签 {deleted} 行")

        documents = load_corpus()
        for document in documents:
            bookmark, _ = bookmark_service.create_bookmark(
                owner=owner,
                url=document["url"],
                title=document["title"],
                description=document.get("description", ""),
                tag_names=document.get("tags", []),
            )
            DocumentContent.objects.update_or_create(
                bookmark=bookmark,
                defaults={
                    "text": document["text"],
                    "status": DocumentContent.STATUS_READY,
                    "content_hash": f"eval-{document['key']}",
                },
            )

        self.stdout.write(
            f"已导入 {len(documents)} 篇语料到用户 {owner.username} 的书签库"
        )
