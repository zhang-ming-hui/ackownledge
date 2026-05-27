"""IR 检索引擎的核心实现。

该模块包含两条主链路：
1. `build_index`：把共享技能数据集转换为 TF-IDF 与 BM25 共用的倒排索引。
2. `search`：对用户查询执行分词、扩展、打分、融合、加权和去重，输出最终排序结果。
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from typing import Dict, List, Tuple

from .config import IRConfig
from .state import save_json_atomic
from .text import expand_query_tokens, normalize_text, safe_number, tokenize, weighted_terms


INDEX_SCHEMA_VERSION = 3


class SkillsIRSystem:
    """基于 TF-IDF 与 BM25 的混合检索引擎。

    设计目标不是做通用搜索库，而是围绕当前 skills 数据集提供：
    - 可解释的离线索引结构；
    - 对中文/英文混合查询友好的轻量检索；
    - 可通过分数组件和规则加权进行调试的排序结果。
    """

    def __init__(self, config: IRConfig) -> None:
        """初始化索引结构和运行参数，但不立即加载数据。"""
        self.config = config
        self.data_path = config.paths.data_file
        self.index_path = config.paths.index_file
        self.documents: List[Dict] = []
        self.postings: Dict[str, Dict[str, float]] = {}
        self.idf: Dict[str, float] = {}
        self.doc_norms: Dict[str, float] = {}
        self.skill_name_counts: Counter = Counter()
        self.index_version: int = 0
        self.bm25_idf: Dict[str, float] = {}
        self.bm25_tf: Dict[str, Dict[str, float]] = {}
        self.doc_lengths: Dict[str, int] = {}
        self.avg_doc_length: float = 0.0
        self.bm25_k1: float = 1.5
        self.bm25_b: float = 0.75

    def load_or_build(self) -> None:
        """优先复用磁盘索引，必要时回退到重新构建。"""
        if self._can_reuse_index():
            try:
                self._load_index()
                return
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                pass
        self.build_index()

    def _can_reuse_index(self) -> bool:
        """判断当前磁盘索引是否满足“存在、较新、结构兼容”三个条件。"""
        if not self.index_path.exists() or not self.data_path.exists():
            return False
        if self.index_path.stat().st_mtime < self.data_path.stat().st_mtime:
            return False
        try:
            with self.index_path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            return False
        return self._is_compatible_index_payload(payload)

    @staticmethod
    def _is_compatible_index_payload(payload: Dict) -> bool:
        """校验索引文件是否包含当前版本所需的关键字段。"""
        required_keys = {
            "documents",
            "postings",
            "idf",
            "doc_norms",
            "bm25_idf",
            "bm25_tf",
            "doc_lengths",
            "avg_doc_length",
            "index_version",
        }
        if not required_keys.issubset(payload.keys()):
            return False
        return int(payload.get("index_version", 0)) >= INDEX_SCHEMA_VERSION

    def _refresh_document_stats(self) -> None:
        """刷新 skill 名称统计，用于结果去重与重复度提示。"""
        self.skill_name_counts = Counter(
            normalize_text(str(doc.get("skill_name", "")))
            for doc in self.documents
            if str(doc.get("skill_name") or "").strip()
        )

    @staticmethod
    def _has_cjk(text: str) -> bool:
        """判断查询中是否包含中日韩统一表意文字。"""
        return bool(re.search(r"[\u4e00-\u9fff]", text))

    def _hybrid_bm25_weight(self, query: str, query_tokens: List[str]) -> float:
        """根据查询形态动态决定混合检索里 BM25 的占比。"""
        token_count = len({token for token in query_tokens if len(token) > 1})
        has_cjk = self._has_cjk(query)

        if has_cjk:
            return 0.02

        if token_count <= 2:
            return 0.08
        if token_count <= 4:
            return 0.10
        if token_count <= 8:
            return 0.12
        return 0.14

    def _load_index(self) -> None:
        """从磁盘加载已经构建好的索引结构。"""
        with self.index_path.open("r", encoding="utf-8") as file:
            payload = json.load(file)

        if not self._is_compatible_index_payload(payload):
            raise ValueError("Index schema is outdated or incomplete")

        self.documents = list(payload["documents"])
        self.postings = {
            term: {doc_id: float(weight) for doc_id, weight in doc_map.items()}
            for term, doc_map in payload["postings"].items()
        }
        self.idf = {token: float(value) for token, value in payload["idf"].items()}
        self.doc_norms = {
            doc_id: float(value) for doc_id, value in payload["doc_norms"].items()
        }
        self.index_version = int(payload.get("index_version", 0))
        self.bm25_idf = {
            token: float(value)
            for token, value in payload["bm25_idf"].items()
        }
        self.bm25_tf = {
            term: {doc_id: float(tf) for doc_id, tf in doc_map.items()}
            for term, doc_map in payload["bm25_tf"].items()
        }
        self.doc_lengths = {
            doc_id: int(value) for doc_id, value in payload["doc_lengths"].items()
        }
        self.avg_doc_length = float(payload.get("avg_doc_length") or 0.0)
        self._refresh_document_stats()

    def build_index(self) -> Dict[str, int]:
        """基于共享数据集构建 TF-IDF 与 BM25 所需的全部索引结构。"""
        with self.data_path.open("r", encoding="utf-8") as file:
            self.documents = json.load(file)

        self._refresh_document_stats()
        doc_term_counts: Dict[str, Counter] = {}
        doc_freq: Counter = Counter()

        # 第一阶段：把每个文档映射为带字段权重的 term 统计。
        for doc in self.documents:
            doc_id = str(doc["skill_id"])
            term_counts = weighted_terms(doc, self.config)
            doc_term_counts[doc_id] = term_counts
            for term in term_counts:
                doc_freq[term] += 1

        doc_count = len(self.documents)
        self.index_version = INDEX_SCHEMA_VERSION

        self.idf = {
            term: math.log((doc_count + 1) / (freq + 1)) + 1.0
            for term, freq in doc_freq.items()
        }

        postings: Dict[str, Dict[str, float]] = defaultdict(dict)
        doc_norms: Dict[str, float] = {}
        # 第二阶段：为 TF-IDF 计算每个 term 在文档中的权重和文档向量范数。
        for doc_id, term_counts in doc_term_counts.items():
            norm_square = 0.0
            for term, tf in term_counts.items():
                weight = (1.0 + math.log(tf)) * self.idf[term]
                postings[term][doc_id] = weight
                norm_square += weight * weight
            doc_norms[doc_id] = math.sqrt(norm_square) if norm_square else 1.0

        self.postings = dict(postings)
        self.doc_norms = doc_norms

        self.bm25_idf = {
            term: math.log((doc_count - freq + 0.5) / (freq + 0.5) + 1.0)
            for term, freq in doc_freq.items()
        }
        bm25_tf: Dict[str, Dict[str, float]] = defaultdict(dict)
        doc_lengths: Dict[str, int] = {}
        total_length = 0

        # 第三阶段：整理 BM25 需要的词频、文档长度和平均文档长度。
        for doc_id, term_counts in doc_term_counts.items():
            doc_len = sum(term_counts.values())
            doc_lengths[doc_id] = int(doc_len)
            total_length += doc_len
            for term, tf in term_counts.items():
                bm25_tf[term][doc_id] = float(tf)

        self.bm25_tf = dict(bm25_tf)
        self.doc_lengths = doc_lengths
        self.avg_doc_length = total_length / max(doc_count, 1)

        payload = {
            "index_version": self.index_version,
            "source_record_count": doc_count,
            "source_data_mtime": self.data_path.stat().st_mtime,
            "documents": self.documents,
            "postings": self.postings,
            "idf": self.idf,
            "doc_norms": self.doc_norms,
            "bm25_idf": self.bm25_idf,
            "bm25_tf": self.bm25_tf,
            "doc_lengths": self.doc_lengths,
            "avg_doc_length": self.avg_doc_length,
        }
        save_json_atomic(self.index_path, payload)
        return self.summary()

    def summary(self) -> Dict[str, int | float]:
        """返回索引规模和统计摘要，便于日志与报告输出。"""
        return {
            "index_version": self.index_version,
            "document_count": len(self.documents),
            "unique_skill_name_count": len(self.skill_name_counts),
            "posting_term_count": len(self.postings),
            "idf_term_count": len(self.idf),
            "bm25_term_count": len(self.bm25_idf),
            "avg_doc_length": round(self.avg_doc_length, 4),
        }

    def _bm25_score(self, query_tokens: List[str]) -> Dict[str, float]:
        """计算查询在所有候选文档上的 BM25 原始得分。"""
        scores: Dict[str, float] = defaultdict(float)
        k1 = self.bm25_k1
        b = self.bm25_b
        avgdl = self.avg_doc_length or 1.0

        query_counts = Counter(t for t in query_tokens if t in self.bm25_idf)
        for term in query_counts:
            idf_val = self.bm25_idf.get(term, 0.0)
            for doc_id, tf in self.bm25_tf.get(term, {}).items():
                dl = self.doc_lengths.get(doc_id, int(avgdl))
                numerator = tf * (k1 + 1)
                denominator = tf + k1 * (1 - b + b * dl / avgdl)
                scores[doc_id] += idf_val * numerator / denominator
        return dict(scores)

    def search(self, query: str, top_k: int | None = None, mode: str = "hybrid") -> List[Dict]:
        """执行一次检索，并返回按最终得分排序的结果列表。"""
        top_k = top_k or self.config.default_top_k
        base_tokens = tokenize(query, self.config)
        query_tokens = expand_query_tokens(base_tokens, self.config, raw_query=query)
        query_counts = Counter(token for token in query_tokens if token in self.idf)
        if not query_counts:
            return []

        query_weights: Dict[str, float] = {}
        query_norm_square = 0.0
        # 先把查询向量映射到与文档相同的 TF-IDF 空间。
        for term, tf in query_counts.items():
            weight = (1.0 + math.log(tf)) * self.idf[term]
            query_weights[term] = weight
            query_norm_square += weight * weight
        query_norm = math.sqrt(query_norm_square) or 1.0

        tfidf_scores: Dict[str, float] = defaultdict(float)
        # 对倒排表做稀疏累加，避免遍历所有文档。
        for term, q_weight in query_weights.items():
            for doc_id, d_weight in self.postings.get(term, {}).items():
                tfidf_scores[doc_id] += q_weight * d_weight

        for doc_id in list(tfidf_scores.keys()):
            tfidf_scores[doc_id] /= query_norm * self.doc_norms.get(doc_id, 1.0)

        bm25_scores = self._bm25_score(query_tokens) if self.bm25_idf else {}
        all_doc_ids = set(tfidf_scores.keys()) | set(bm25_scores.keys())
        if not all_doc_ids:
            return []

        # BM25 原始分布通常与余弦相似度量纲不同，先归一化再做融合。
        bm25_max = max(bm25_scores.values()) if bm25_scores else 1.0
        bm25_max = bm25_max or 1.0
        docs_by_id = {str(doc["skill_id"]): doc for doc in self.documents}

        raw_results: List[Dict] = []
        for doc_id in all_doc_ids:
            doc = docs_by_id.get(doc_id)
            if not doc:
                continue

            cosine = tfidf_scores.get(doc_id, 0.0)
            bm25_raw = bm25_scores.get(doc_id, 0.0)
            bm25_norm = bm25_raw / bm25_max

            if mode == "tfidf":
                base_score = cosine
            elif mode == "bm25":
                base_score = bm25_norm
            else:
                bm25_weight = self._hybrid_bm25_weight(query, query_tokens)
                base_score = (1.0 - bm25_weight) * cosine + bm25_weight * bm25_norm

            # 规则加权用于弥补纯向量/统计打分对标题精确命中和热度的感知不足。
            score = self._apply_boosts(doc, query, query_tokens, base_score)
            skill_name = str(doc.get("skill_name", "")).strip()
            skill_key = normalize_text(skill_name) or doc_id

            raw_results.append(
                {
                    "score": score,
                    "cosine_score": cosine,
                    "bm25_score": bm25_raw,
                    "skill_id": doc_id,
                    "skill_name": skill_name,
                    "skill_name_key": skill_key,
                    "duplicate_count": int(self.skill_name_counts.get(skill_key, 1)),
                    "category": doc.get("category", ""),
                    "owner": doc.get("owner", ""),
                    "repo": doc.get("repo", ""),
                    "description": doc.get("description", ""),
                    "detail_url": doc.get("detail_url", ""),
                    "first_seen": doc.get("first_seen", ""),
                    "weekly_installs_num": doc.get("weekly_installs_num", 0),
                    "github_stars_num": doc.get("github_stars_num", 0),
                    "snippet": self._make_snippet(doc, query_tokens),
                }
            )

        raw_results.sort(
            key=lambda item: (
                -float(item["score"]),
                str(item["skill_name"]).lower(),
                str(item["skill_id"]),
            )
        )

        deduped: List[Dict] = []
        seen_keys = set()
        # 同名 skill 往往来自重复抓取或多版本镜像，这里只保留最高分的一条。
        for item in raw_results:
            key = item["skill_name_key"]
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(item)
            if len(deduped) >= top_k:
                break

        return deduped

    def _apply_boosts(
        self,
        doc: Dict,
        query: str,
        query_tokens: List[str],
        cosine_score: float,
    ) -> float:
        """在基础相关性分上叠加规则化提升因子。"""
        score = cosine_score
        normalized_query = normalize_text(query)
        title = normalize_text(str(doc.get("skill_name", "")))
        description = normalize_text(str(doc.get("description", "")))
        category = normalize_text(str(doc.get("category", "")))

        if normalized_query and normalized_query in title:
            score += 0.25
        if normalized_query and normalized_query in description:
            score += 0.12
        if any(token in category for token in query_tokens if len(token) > 1):
            score += 0.05

        if any(token == title for token in query_tokens if len(token) > 1) and (
            self._has_cjk(query) or len({token for token in query_tokens if len(token) > 1}) <= 4
        ):
            score += 0.22

        title_hits = {token for token in query_tokens if len(token) > 1 and token in title}
        description_hits = {
            token
            for token in query_tokens
            if len(token) > 1 and token in description and token not in title_hits
        }
        score += min(len(title_hits) * 0.12, 0.36)
        score += min(len(description_hits) * 0.02, 0.12)

        unique_query_tokens = [token for token in dict.fromkeys(query_tokens) if len(token) > 1]
        if unique_query_tokens:
            coverage_hits = sum(
                1 for token in unique_query_tokens if token in title or token in description
            )
            score += min((coverage_hits / len(unique_query_tokens)) * 0.3, 0.3)

        for boost_rule in self.config.phrase_boosts:
            triggers = [normalize_text(str(item)) for item in boost_rule.get("triggers", [])]
            if not any(trigger and trigger in normalized_query for trigger in triggers):
                continue

            target_keywords = [
                normalize_text(str(item)) for item in boost_rule.get("target_keywords", [])
            ]
            if any(keyword and keyword in title for keyword in target_keywords):
                score += float(boost_rule.get("title_boost", 0.0))
            elif any(keyword and keyword in description for keyword in target_keywords):
                score += float(boost_rule.get("description_boost", 0.0))

        popularity = (
            math.log1p(safe_number(doc.get("weekly_installs_num", 0))) * 0.006
            + math.log1p(safe_number(doc.get("github_stars_num", 0))) * 0.005
        )
        return score + popularity

    def _make_snippet(self, doc: Dict, query_tokens: List[str]) -> str:
        """从描述中选择与查询最相关的句子作为摘要片段。"""
        description = str(doc.get("description", "")).strip()
        if not description:
            return f"{doc.get('skill_name', '')} | {doc.get('category', '')}".strip(" |")

        sentences = re.split(r"(?<=[.!?。；;])\s+", description)
        if not sentences:
            return description[:180]

        scored_sentences: List[Tuple[int, str]] = []
        for sentence in sentences:
            normalized_sentence = normalize_text(sentence)
            hit_count = sum(
                1 for token in query_tokens if len(token) > 1 and token in normalized_sentence
            )
            scored_sentences.append((hit_count, sentence.strip()))

        scored_sentences.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
        best = scored_sentences[0][1]
        return best[:220] + ("..." if len(best) > 220 else "")


def print_results(query: str, results: List[Dict]) -> None:
    """以终端友好的方式输出检索结果。"""
    print(f"\nQuery: {query}")
    if not results:
        print("没有检索到匹配结果。")
        return

    for index, item in enumerate(results, start=1):
        print(f"\n[{index}] {item['skill_name']}  score={item['score']:.4f}")
        print(
            f"    category: {item['category']} | owner: {item['owner']} | repo: {item['repo']}"
        )
        print(
            f"    cosine: {item['cosine_score']:.4f} | bm25: {item.get('bm25_score', 0):.4f}"
        )
        if item.get("duplicate_count", 1) > 1:
            print(f"    duplicate_count: {item['duplicate_count']}")
        print(
            f"    weekly_installs: {item['weekly_installs_num']} | "
            f"github_stars: {item['github_stars_num']} | first_seen: {item['first_seen']}"
        )
        print(f"    url: {item['detail_url']}")
        print(f"    match: {item['snippet']}")
