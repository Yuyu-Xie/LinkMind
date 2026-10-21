from __future__ import annotations

import re

from evaluation.services.text import (
    containment_bigrams,
    jaccard_bigrams,
    normalize_for_match,
)
from research.models import ClaimEvidence, ResearchTask

CITATION_RE = re.compile(r"\[e:(\d+)\]")
QUOTE_MATCH_THRESHOLD = 0.7
STRICT_PRECISION = 0.8
STRICT_COVERAGE = 0.6


def _fact_variants(fact) -> list[str]:
    if isinstance(fact, str):
        return [fact]
    if isinstance(fact, dict):
        variants = fact.get("any") or []
        return [item for item in variants if isinstance(item, str)]
    return []


def _reference_evidence(case: dict) -> list[dict]:
    return list(case.get("reference_evidence") or [])


def _quote_matches(quote: str, reference_quote: str) -> bool:
    """Match a citation against a reference quote.

    Jaccard alone rejects a correct short reference embedded in a longer
    evidence passage, which is the normal shape for baseline citations.
    Accept either high Jaccard or high containment of the shorter text.
    """
    return (
        jaccard_bigrams(quote, reference_quote) >= QUOTE_MATCH_THRESHOLD
        or containment_bigrams(quote, reference_quote) >= 0.8
    )


def _citation_quality(task: ResearchTask, content: str, case: dict) -> dict:
    evidence_map = {
        item.id: item for item in task.evidence.select_related("source").all()
    }
    markers = [int(item) for item in CITATION_RE.findall(content)]
    references = _reference_evidence(case)
    reference_urls = set(case.get("reference_sources") or [])

    matched_references: set[int] = set()
    correct = 0
    for marker in markers:
        evidence = evidence_map.get(marker)
        if evidence is None:
            continue
        if evidence.source.url not in reference_urls:
            continue
        for index, reference in enumerate(references):
            if reference["url"] != evidence.source.url:
                continue
            if _quote_matches(evidence.quote, reference["quote"]):
                correct += 1
                matched_references.add(index)
                break

    total = len(markers)
    precision = correct / total if total else 0.0
    recall = len(matched_references) / len(references) if references else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "markers": markers,
        "evidence_total": len(evidence_map),
        "citation_total": total,
        "citation_correct": correct,
        "invalid_markers": [item for item in markers if item not in evidence_map],
        "matched_references": len(matched_references),
        "reference_total": len(references),
        "citation_precision": round(precision, 4),
        "citation_recall": round(recall, 4),
        "citation_f1": round(f1, 4),
    }


def _claim_support(task: ResearchTask) -> tuple[float, list[str]]:
    claims = list(task.claims.prefetch_related("links").all())
    if not claims:
        return 0.0, []
    supported = [
        item
        for item in claims
        if any(link.relation == ClaimEvidence.REL_SUPPORTS for link in item.links.all())
    ]
    texts = [item.text for item in supported]
    return round(len(supported) / len(claims), 4), texts


def _key_fact_coverage(report_text: str, supported_claims: list[str], case: dict) -> dict:
    combined = normalize_for_match(report_text + "\n" + "\n".join(supported_claims))
    facts: list[str] = []
    for reference in _reference_evidence(case):
        for fact in reference.get("key_facts") or []:
            facts.append(fact)

    covered: list[str] = []
    missing: list[str] = []
    for fact in facts:
        variants = _fact_variants(fact)
        if not variants:
            continue
        if any(normalize_for_match(item) in combined for item in variants):
            covered.append(variants[0])
        else:
            missing.append(variants[0])

    total = len(covered) + len(missing)
    coverage = len(covered) / total if total else 0.0
    return {
        "coverage": round(coverage, 4),
        "covered": covered,
        "missing": missing,
        "total": total,
    }


def evaluate_task(task: ResearchTask, case: dict) -> dict:
    task.refresh_from_db()
    report = getattr(task, "report", None)
    content = report.content_md if report else ""

    citation = _citation_quality(task, content or "", case)
    support_rate, supported_claims = _claim_support(task)
    coverage = _key_fact_coverage(content or "", supported_claims, case)

    has_parseable_citation = bool(citation["markers"]) and not citation[
        "invalid_markers"
    ]
    completed = bool(
        task.status == ResearchTask.STATUS_COMPLETED
        and (content or "").strip()
        and has_parseable_citation
    )
    strict_completed = bool(
        completed
        and citation["citation_precision"] >= STRICT_PRECISION
        and coverage["coverage"] >= STRICT_COVERAGE
    )

    return {
        "completed": completed,
        "strict_completed": strict_completed,
        "citation_precision": citation["citation_precision"],
        "citation_recall": citation["citation_recall"],
        "citation_f1": citation["citation_f1"],
        "claim_support_rate": support_rate,
        "key_fact_coverage": coverage["coverage"],
        "tokens": task.tokens_used,
        "latency_ms": task.duration_ms or 0,
        "details": {
            "task_status": task.status,
            "completion_reason": task.completion_reason,
            "is_partial": task.is_partial,
            "citations": citation,
            "key_facts": coverage,
            "supported_claims": len(supported_claims),
            "report_chars": len(content or ""),
        },
    }
