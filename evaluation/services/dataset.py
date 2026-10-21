from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

DATA_DIR = Path(settings.BASE_DIR) / "evaluation" / "data"
CORPUS_DIR = DATA_DIR / "corpus"
DATASETS_DIR = DATA_DIR / "datasets"


@dataclass
class Dataset:
    name: str
    version: str
    description: str
    cases: list[dict]
    sha256: str


def load_corpus() -> list[dict]:
    documents = []
    for path in sorted(CORPUS_DIR.glob("*.json")):
        with path.open("r", encoding="utf-8") as handle:
            document = json.load(handle)
        for field in ("key", "url", "title", "text"):
            if not document.get(field):
                raise ValueError(f"语料 {path.name} 缺少字段 {field}")
        documents.append(document)
    return documents


def load_dataset(name: str = "linkmind_v1") -> Dataset:
    path = DATASETS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"数据集不存在: {path}")
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    cases = payload.get("cases") or []
    if not cases:
        raise ValueError(f"数据集 {name} 没有用例")

    seen: set[str] = set()
    for case in cases:
        for field in (
            "key",
            "question",
            "reference_sources",
            "reference_evidence",
            "reference_answer",
        ):
            if not case.get(field):
                raise ValueError(f"用例 {case.get('key', '?')} 缺少字段 {field}")
        if case["key"] in seen:
            raise ValueError(f"用例 key 重复: {case['key']}")
        seen.add(case["key"])
        for evidence in case["reference_evidence"]:
            if not evidence.get("quote") or not evidence.get("url"):
                raise ValueError(f"用例 {case['key']} 的参考证据缺少 quote 或 url")

    return Dataset(
        name=name,
        version=payload.get("version", name),
        description=payload.get("description", ""),
        cases=cases,
        sha256=hashlib.sha256(raw).hexdigest(),
    )
