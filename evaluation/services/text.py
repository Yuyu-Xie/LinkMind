from __future__ import annotations

import re

CJK_RE = re.compile(r"[一-鿿]")
ASCII_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_+.#-]*")
PUNCT_RE = re.compile(r"[\s\W_]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    lowered = (text or "").lower()
    words = ASCII_WORD_RE.findall(lowered)
    cjk_chars = CJK_RE.findall(lowered)
    bigrams = [
        cjk_chars[index] + cjk_chars[index + 1]
        for index in range(len(cjk_chars) - 1)
    ]
    return words + bigrams + cjk_chars


def normalize_for_match(text: str) -> str:
    return PUNCT_RE.sub("", (text or "").lower())


def char_bigrams(text: str) -> set[str]:
    normalized = normalize_for_match(text)
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[index : index + 2] for index in range(len(normalized) - 1)}


def jaccard_bigrams(left: str, right: str) -> float:
    left_set = char_bigrams(left)
    right_set = char_bigrams(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def containment_bigrams(left: str, right: str) -> float:
    """Share of the shorter text's bigrams present in the longer one."""
    left_set = char_bigrams(left)
    right_set = char_bigrams(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / min(len(left_set), len(right_set))


def split_passages(text: str, max_chars: int = 1200) -> list[str]:
    blocks = [block.strip() for block in re.split(r"\n\s*\n", text or "") if block.strip()]
    passages: list[str] = []
    for block in blocks:
        if len(block) <= max_chars:
            passages.append(block)
            continue
        for start in range(0, len(block), max_chars):
            chunk = block[start : start + max_chars].strip()
            if chunk:
                passages.append(chunk)
    return [item for item in passages if len(item) >= 20]
