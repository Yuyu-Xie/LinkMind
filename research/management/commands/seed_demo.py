from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from bookmarks.models import DocumentContent
from bookmarks.services import bookmarks as bookmark_service
from research.models import ResearchTask

DEMO_BOOKMARKS = [
    {
        "url": "https://example.com/postgres-index-types",
        "title": "PostgreSQL 索引类型与适用场景",
        "description": "B-tree、Hash、GIN、GiST、BRIN 的差异与选择",
        "tags": ["postgresql", "数据库"],
        "text": (
            "PostgreSQL 的默认索引类型是 B-tree。B-tree 支持等值查询、范围查询和排序，"
            "适用于大多数 OLTP 场景，例如 WHERE id = 1、WHERE created_at > '2024-01-01'、"
            "ORDER BY created_at。\n\n"
            "Hash 索引只支持等值比较，索引体积通常小于 B-tree，但在 PostgreSQL 10 之前"
            "不支持 WAL 复制。\n\n"
            "GIN 是倒排索引，适合数组、JSONB、tsvector 全文检索，以及 pg_trgm 模糊匹配。"
            "GIN 写入成本较高，适合读多写少的场景。\n\n"
            "GiST 支持几何类型、范围类型和最近邻查询，PostGIS 的空间索引建立在 GiST 上。\n\n"
            "BRIN 保存每个数据块的摘要，体积很小，适合按物理顺序写入的时间序列数据。"
            "查询选择性高时 BRIN 效果差，需要配合 ORDER BY 时间列使用。"
        ),
    },
    {
        "url": "https://example.com/postgres-explain",
        "title": "读懂 PostgreSQL EXPLAIN ANALYZE",
        "description": "执行计划中的代价、行数估算与常见扫描方式",
        "tags": ["postgresql", "性能"],
        "text": (
            "EXPLAIN 展示查询计划，EXPLAIN ANALYZE 会实际执行并返回耗时。"
            "Seq Scan 表示顺序扫描整张表，Index Scan 通过索引定位行，"
            "Bitmap Heap Scan 先收集匹配的页面位图再回表。\n\n"
            "cost 是规划器的估算代价，第一项是启动代价，第二项是总代价。"
            "rows 是估算返回行数，如果估算与实际差距大，统计信息可能过期，可以执行 ANALYZE。\n\n"
            "Buffers 显示共享缓冲区命中情况。shared read 高说明数据不在缓存中，"
            "可能需要检查索引或增加 shared_buffers。"
        ),
    },
    {
        "url": "https://example.com/redis-persistence",
        "title": "Redis 持久化：RDB 与 AOF",
        "description": "两种持久化机制的写入时机、恢复速度与取舍",
        "tags": ["redis", "架构"],
        "text": (
            "Redis 提供 RDB 和 AOF 两种持久化方式。RDB 在指定时间间隔生成数据快照，"
            "文件紧凑，恢复速度快，但两次快照之间的数据可能丢失。\n\n"
            "AOF 追加写命令日志，可以配置 everysec 每秒刷盘，最多丢失约一秒数据。"
            "AOF 文件通常大于 RDB，恢复时需要重放命令。Redis 7 使用 multi-part AOF，"
            "把基础快照与增量日志分开管理。\n\n"
            "生产环境常见组合是同时开启 RDB 和 AOF。RDB 用于备份与快速恢复，"
            "AOF 用于降低数据丢失窗口。只使用 RDB 时，主从切换可能丢失较多数据。"
        ),
    },
    {
        "url": "https://example.com/django-async-tasks",
        "title": "Django 异步任务与 Huey",
        "description": "为什么把长任务移出请求周期，以及 Huey 的基本用法",
        "tags": ["django", "python", "架构"],
        "text": (
            "Web 请求应该在数百毫秒内返回。抓取网页、调用大模型、生成报告这类操作"
            "耗时从数秒到数分钟，放在请求周期内会占满 worker，导致超时和重试。\n\n"
            "Huey 是轻量任务队列，任务序列化后写入 Redis，由独立消费者进程执行。"
            "Django 项目中通过 HUEY 配置连接 RedisHuey，使用 @task 装饰器登记任务，"
            "用 manage.py run_huey 启动消费者。\n\n"
            "任务参数应尽量小，通常只传主键，业务状态写入数据库。这样任务重放时"
            "可以从数据库恢复状态，而不是依赖队列中的序列化数据。"
        ),
    },
    {
        "url": "https://example.com/rag-agent-design",
        "title": "检索增强生成与工具调用 Agent 的设计要点",
        "description": "规划、检索、证据、引用与终止条件",
        "tags": ["llm", "agent", "rag"],
        "text": (
            "检索增强生成把外部资料放入上下文，降低模型编造事实的概率。"
            "基础流程是：切分文档、向量化、按问题检索、把片段拼入提示词、生成回答。\n\n"
            "多步 Agent 在此基础上增加工具调用与循环控制。每一轮模型选择工具，"
            "执行结果回填上下文，直到满足终止条件。常见工具包括关键词检索、文档读取、"
            "证据摘取和主张记录。\n\n"
            "引用可追溯要求每条结论绑定到原始片段。实现上给证据分配稳定 ID，"
            "要求模型输出 [e:12] 形式的标记，后端解析并校验 ID 是否属于本次任务。\n\n"
            "上下文管理决定成本上限。每轮从数据库重建结构化状态，只保留关键证据与"
            "未解决问题，避免把完整历史反复送入模型。"
        ),
    },
    {
        "url": "https://example.com/bm25-baseline",
        "title": "BM25 作为检索基线",
        "description": "词频、逆文档频率与文档长度归一化",
        "tags": ["检索", "评测"],
        "text": (
            "BM25 是基于词频的排序函数，综合词频饱和、逆文档频率和文档长度归一化。"
            "常见参数 k1 取 1.2 到 2.0，b 取 0.75。\n\n"
            "BM25 不依赖向量模型，计算成本低，适合作为检索系统的对照基线。"
            "在评测中固定语料、固定分词和固定 Top K，可以复现实验并比较不同策略。\n\n"
            "BM25 对同义词和语义改写不敏感。动态 Agent 通过多轮改写查询和读取文档，"
            "通常能在多跳问题上超过单次 BM25 检索，但 token 消耗和延迟更高。"
        ),
    },
]


class Command(BaseCommand):
    help = "创建演示用户、书签和本地正文，便于离线演示"

    def add_arguments(self, parser):
        parser.add_argument("--username", default="demo")
        parser.add_argument("--password", default="linkmind123")

    @transaction.atomic
    def handle(self, *args, **options):
        user_model = get_user_model()
        user, created = user_model.objects.get_or_create(
            username=options["username"],
            defaults={"is_staff": True},
        )
        if created:
            user.set_password(options["password"])
            user.save(update_fields=["password"])
            self.stdout.write(f"创建用户 {user.username} / {options['password']}")
        else:
            self.stdout.write(f"用户 {user.username} 已存在")

        for item in DEMO_BOOKMARKS:
            bookmark, _ = bookmark_service.create_bookmark(
                owner=user,
                url=item["url"],
                title=item["title"],
                description=item["description"],
                tag_names=item["tags"],
            )
            DocumentContent.objects.update_or_create(
                bookmark=bookmark,
                defaults={
                    "text": item["text"],
                    "status": DocumentContent.STATUS_READY,
                    "content_hash": f"demo-{bookmark.pk}",
                },
            )

        ResearchTask.objects.filter(owner=user).delete()
        self.stdout.write(
            f"已写入 {len(DEMO_BOOKMARKS)} 条演示书签，并清空该用户的旧研究任务"
        )
