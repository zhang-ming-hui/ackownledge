'''
中文分词和查询扩展
'''

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, Iterable, List

from .config import IRConfig


FALLBACK_QUERY_EXPANSIONS = {
    "\u5e02\u573a": ["market", "research", "analysis", "business"],
    "\u7814\u7a76": ["research", "analysis", "study"],
    "\u5e02\u573a\u7814\u7a76": ["market", "research", "reports", "analysis"],
    "\u5e02\u573a\u7814\u7a76\u62a5\u544a": ["market", "research", "reports", "analysis", "document"],
    "\u5411\u91cf": ["vector", "embedding", "retrieval", "semantic"],
    "\u5411\u91cf\u6570\u636e\u5e93": ["vector", "database", "qdrant", "embedding", "retrieval"],
    "\u6587\u6863\u5904\u7406": ["pdf", "document", "extract", "convert"],
    "sql": ["sql", "query", "database", "postgres"],
    "sql queries": ["sql", "query", "database", "postgres"],
}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def safe_number(value: object) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _english_variants(token: str) -> List[str]:
    variants = [token]
    for part in re.split(r"[-_./+]+", token):
        if part and part not in variants:
            variants.append(part)

    for candidate in list(variants):
        if candidate.endswith("ies") and len(candidate) > 4:
            stem = candidate[:-3] + "y"
        elif candidate.endswith("s") and len(candidate) > 3 and not candidate.endswith("ss"):
            stem = candidate[:-1]
        else:
            stem = ""
        if stem and stem not in variants:
            variants.append(stem)

    return variants

# 提取中文块，将中文拆成整词、单词、双字片段
def tokenize(text: str, config: IRConfig) -> List[str]:
    tokens: List[str] = []
    if not text:
        return tokens

    normalized = normalize_text(text)
    english_tokens = re.findall(r"[a-z0-9][a-z0-9+#._-]*", normalized)
    chinese_chunks = re.findall(r"[\u4e00-\u9fff]+", normalized)

    for token in english_tokens:
        if token not in config.stopwords and len(token) > 1:
            for variant in _english_variants(token):
                if variant not in config.stopwords and len(variant) > 1:
                    tokens.append(variant)

    for chunk in chinese_chunks:
        if chunk not in config.stopwords:
            tokens.append(chunk)
        if len(chunk) > 1:
            tokens.extend(chunk)
            tokens.extend(chunk[i : i + 2] for i in range(len(chunk) - 1))

    return tokens


def expand_query_tokens(
    tokens: Iterable[str],
    config: IRConfig,
    raw_query: str = "",
) -> List[str]:
    expanded = list(tokens)
    for token in list(tokens):
        expanded.extend(config.query_expansions.get(token, []))
        expanded.extend(config.english_query_expansions.get(token, []))
        expanded.extend(FALLBACK_QUERY_EXPANSIONS.get(token, []))

    normalized_query = normalize_text(raw_query)
    for phrase, additions in config.query_expansions.items():
        if phrase in normalized_query:
            expanded.extend(additions)
    for phrase, additions in config.english_query_expansions.items():
        if phrase in normalized_query:
            expanded.extend(additions)
    for phrase, additions in FALLBACK_QUERY_EXPANSIONS.items():
        if phrase in normalized_query:
            expanded.extend(additions)
    return expanded


def weighted_terms(document: Dict[str, str], config: IRConfig) -> Counter:
    counts: Counter = Counter()
    for field, weight in config.field_weights.items():
        for token in tokenize(str(document.get(field, "")), config):
            counts[token] += weight
    return counts
