from __future__ import annotations

import logging

from django.conf import settings
from django.db import close_old_connections
from huey import crontab
from huey.contrib.djhuey import HUEY, db_periodic_task, db_task

from research.services.locking import TaskLocked, task_lock
from research.services.runner import recover_stale_tasks, run_task

logger = logging.getLogger("research")


def _lock_ttl() -> int:
    """Redis lock must outlive the longest allowed run; DB lease stays authoritative."""
    return settings.RESEARCH_TIMEOUT_SECONDS + 300


@db_task(retries=0)
def run_research_task(task_id: int) -> str | None:
    """Execute one research task. Only the primary key travels through Redis."""
    try:
        with task_lock(f"research-task-{task_id}", ttl=_lock_ttl()):
            return run_task(task_id)
    except TaskLocked:
        # Another worker holds the lock; the database lease remains authoritative.
        logger.info("task %s is locked by another worker, skip", task_id)
        return "locked"
    finally:
        close_old_connections()


@db_periodic_task(crontab(minute="*"))
def sweep_stale_tasks() -> int:
    count = recover_stale_tasks()
    if count:
        logger.warning("sweeper requeued %s stale tasks", count)
    return count


@HUEY.on_startup()
def recover_on_startup() -> None:
    try:
        count = recover_stale_tasks()
        if count:
            logger.warning("startup recovery requeued %s tasks", count)
    except Exception:  # noqa: BLE001
        logger.exception("startup recovery failed")
