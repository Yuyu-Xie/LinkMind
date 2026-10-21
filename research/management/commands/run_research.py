from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from research.models import ResearchTask
from research.services.runner import run_task


class Command(BaseCommand):
    help = "同步执行一个研究任务（不经过 Huey），用于本地调试"

    def add_arguments(self, parser):
        parser.add_argument("task_id", nargs="?", type=int, help="已有任务 ID")
        parser.add_argument("--question", help="创建并执行新任务的问题")
        parser.add_argument("--user", help="任务所有者用户名，默认取第一个超级用户")
        parser.add_argument(
            "--strategy",
            default=ResearchTask.STRATEGY_AGENT,
            choices=[ResearchTask.STRATEGY_AGENT, ResearchTask.STRATEGY_BASELINE],
        )
        parser.add_argument("--offline", action="store_true", help="禁止网页检索")
        parser.add_argument("--max-steps", type=int, default=None)
        parser.add_argument(
            "--no-retry", action="store_true", help="失败时不重新排队，直接标记失败"
        )

    def handle(self, *args, **options):
        task = self._get_task(options)
        self.stdout.write(f"任务 #{task.pk} 状态 {task.status}，开始同步执行…")

        result = run_task(
            task.pk,
            retry_enabled=not options["no_retry"],
        )
        task.refresh_from_db()

        self.stdout.write(
            f"执行结束：result={result} status={task.status} "
            f"reason={task.completion_reason or '-'} tokens={task.tokens_used}"
        )
        if task.error:
            self.stdout.write(self.style.WARNING(f"错误：{task.error}"))
        report = getattr(task, "report", None)
        if report:
            self.stdout.write("")
            self.stdout.write(report.content_md[:1000])

    def _get_task(self, options) -> ResearchTask:
        if options["task_id"]:
            task = ResearchTask.objects.filter(pk=options["task_id"]).first()
            if task is None:
                raise CommandError(f"任务 {options['task_id']} 不存在")
            if task.status != ResearchTask.STATUS_PENDING:
                raise CommandError(
                    f"任务当前状态是 {task.status}，只有 pending 任务可以同步执行"
                )
            return task

        if not options["question"]:
            raise CommandError("必须提供 task_id 或 --question")

        user_model = get_user_model()
        if options["user"]:
            owner = user_model.objects.filter(username=options["user"]).first()
        else:
            owner = user_model.objects.filter(is_superuser=True).first()
        if owner is None:
            raise CommandError("找不到任务所有者，请用 --user 指定用户名")

        kwargs = {}
        if options["max_steps"]:
            kwargs["max_steps"] = options["max_steps"]
        return ResearchTask.objects.create(
            owner=owner,
            question=options["question"],
            strategy=options["strategy"],
            options={"offline": options["offline"]},
            **kwargs,
        )
