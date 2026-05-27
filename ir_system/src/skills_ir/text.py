"""IR 子系统的文本标准化、分词与查询扩展工具。"""

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
    """统一空白并转小写，作为全文匹配与去重的基础。"""
    return re.sub(r"\s+", " ", text.strip().lower())


def safe_number(value: object) -> float:
    """把各种数值输入尽量安全地转换为浮点数。"""
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _english_variants(token: str) -> List[str]:
    """为英文 token 生成拆分和简化变体，提升召回。"""
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


def tokenize(text: str, config: IRConfig) -> List[str]:
    """对英文和中文混合文本做轻量分词。

    这里不依赖外部分词器，而是采用规则化处理：
    - 英文保留原词、拆分词和简单词干变体。
    - 中文同时保留整段、单字和双字片段。
    - 停用词由配置统一控制。
    """
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
            # 单字和双字片段能在无外部分词器时弥补中文召回不足。
            tokens.extend(chunk)
            tokens.extend(chunk[i : i + 2] for i in range(len(chunk) - 1))

    return tokens


def expand_query_tokens(
    tokens: Iterable[str],
    config: IRConfig,
    raw_query: str = "",
) -> List[str]:
    """根据配置和兜底词典扩展查询词，增强语义召回。"""
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
    """按字段权重汇总文档词频，供索引构建使用。"""
    counts: Counter = Counter()
    for field, weight in config.field_weights.items():
        for token in tokenize(str(document.get(field, "")), config):
            counts[token] += weight
    return counts
