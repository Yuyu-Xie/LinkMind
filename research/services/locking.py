"""Redis 分布式锁。

Huey 3.4 的 `lock_task(ttl=...)` 依赖 Redis 7.4 的 hash-field TTL，Memurai 4.1
(Redis 7.2.5) 不支持。这里用 SET NX EX 实现同样的语义：拿不到锁抛
`TaskLocked`，持锁进程崩溃后锁随 TTL 自动释放。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import redis
from django.conf import settings

logger = logging.getLogger("research")

_RELEASE_SCRIPT = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

_client: redis.Redis | None = None


class TaskLocked(Exception):
    """另一个 worker 已持有该任务的锁。"""


def get_client() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(settings.REDIS_URL)
    return _client


@contextmanager
def task_lock(name: str, ttl: int) -> Iterator[None]:
    """同名锁互斥；ttl 秒后即使未释放也会过期。"""
    client = get_client()
    key = f"linkmind:lock:{name}"
    token = uuid.uuid4().hex
    if not client.set(key, token, nx=True, ex=ttl):
        raise TaskLocked(name)
    try:
        yield
    finally:
        try:
            client.eval(_RELEASE_SCRIPT, 1, key, token)
        except redis.RedisError:
            logger.warning("failed to release lock %s", key, exc_info=True)
