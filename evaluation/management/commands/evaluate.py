from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from evaluation.models import EvaluationRun
from evaluation.services.runner import run_evaluation


class Command(BaseCommand):
    help = "在离线语料上运行基线检索与动态研究 Agent 的对比评测"

    def add_arguments(self, parser):
        parser.add_argument("--dataset", default="linkmind_v1")
        parser.add_argument(
            "--strategies",
            default="baseline,agent",
            help="逗号分隔，可选 baseline,agent",
        )
        parser.add_argument("--runs", type=int, default=1, help="每个策略重复次数")
        parser.add_argument("--user", default="demo", help="评测任务所有者")
        parser.add_argument(
            "--output", default="evaluation/results", help="结果 JSON 输出目录，留空不写文件"
        )

    def handle(self, *args, **options):
        strategies = [
            item.strip() for item in options["strategies"].split(",") if item.strip()
        ]
        valid = {choice[0] for choice in EvaluationRun.STRATEGY_CHOICES}
        unknown = set(strategies) - valid
        if unknown:
            raise CommandError(f"未知策略: {', '.join(sorted(unknown))}")

        owner = get_user_model().objects.filter(username=options["user"]).first()
        if owner is None:
            raise CommandError(f"用户 {options['user']} 不存在，先运行 seed_demo")

        if options["runs"] < 1:
            raise CommandError("--runs 至少为 1")

        runs = run_evaluation(
            dataset_name=options["dataset"],
            strategies=strategies,
            runs=options["runs"],
            owner=owner,
            output_dir=options["output"] or None,
        )

        for run in runs:
            summary = run.summary
            self.stdout.write(
                f"run #{run.pk} {run.dataset} {run.strategy} "
                f"完成率={summary.get('completion_rate')} "
                f"严格完成率={summary.get('strict_completion_rate')} "
                f"引用F1={summary.get('citation_f1')} "
                f"关键事实覆盖={summary.get('key_fact_coverage')} "
                f"平均token={summary.get('avg_tokens')} "
                f"平均耗时={summary.get('avg_latency_ms')}ms"
            )
