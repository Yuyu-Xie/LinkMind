from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

from evaluation.services.text import tokenize


@dataclass
class Passage:
    bookmark_id: int
    url: str
    title: str
    text: str
    score: float = 0.0


class BM25Index:
    def __init__(self, passages: list[Passage], k1: float = 1.2, b: float = 0.75):
        self.passages = passages
        self.k1 = k1
        self.b = b
        self.tokenized = [tokenize(item.text) for item in passages]
        self.lengths = [len(tokens) for tokens in self.tokenized]
        self.avg_length = (sum(self.lengths) / len(self.lengths)) if self.lengths else 0.0
        self.term_frequencies = [Counter(tokens) for tokens in self.tokenized]
        self.document_frequency: Counter[str] = Counter()
        for tokens in self.tokenized:
            self.document_frequency.update(set(tokens))
        self.total_documents = len(passages)

    def _idf(self, term: str) -> float:
        df = self.document_frequency.get(term, 0)
        return math.log(1 + (self.total_documents - df + 0.5) / (df + 0.5))

    def search(self, query: str, limit: int = 5) -> list[Passage]:
        if not self.passages:
            return []
        query_terms = list(dict.fromkeys(tokenize(query)))
        scored: list[Passage] = []
        for index, passage in enumerate(self.passages):
            frequencies = self.term_frequencies[index]
            length = self.lengths[index] or 1
            score = 0.0
            for term in query_terms:
                term_frequency = frequencies.get(term, 0)
                if not term_frequency:
                    continue
                denominator = term_frequency + self.k1 * (
                    1 - self.b + self.b * length / (self.avg_length or 1)
                )
                score += self._idf(term) * term_frequency * (self.k1 + 1) / denominator
            if score > 0:
                scored.append(
                    Passage(
                        bookmark_id=passage.bookmark_id,
                        url=passage.url,
                        title=passage.title,
                        text=passage.text,
                        score=score,
                    )
                )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]
