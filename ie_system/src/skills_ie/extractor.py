'''
从技能描述文本中抽取出平台、语言、动作类型、目标领域、输出格式、指标等结构化信息，
并记录每条提取的证据（规则来源、匹配文本、上下文等）。
它还支持生成报告、搜索提取结果以及保存数据。
下面分模块详细讲解其逻辑。
'''
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from .config import IEConfig
from .state import save_json_atomic, utc_now_iso

# 抽取器的核心思路是“规则命中 + 证据保留”：
# 每个字段不只输出抽取值，还会记录规则来源、命中文本和上下文，
# 方便人工复核、误差分析和自动评测。

ACTION_ALIAS_PATTERNS: List[Tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:analysis|analytics|analyzer|analyst)\b", re.IGNORECASE), "analyze"),
    (re.compile(r"\b(?:optimization|optimizer|optimized)\b", re.IGNORECASE), "optimize"),
    (re.compile(r"\b(?:generation|generator|generated)\b", re.IGNORECASE), "generate"),
    (re.compile(r"\b(?:creation|creator|writing|writer|drafting)\b", re.IGNORECASE), "create"),
    (re.compile(r"\b(?:visualization|visualizer)\b", re.IGNORECASE), "visualize"),
    (re.compile(r"\b(?:validation|validator)\b", re.IGNORECASE), "validate"),
    (re.compile(r"\b(?:detection|detector)\b", re.IGNORECASE), "detect"),
    (re.compile(r"\b(?:comparison|comparator)\b", re.IGNORECASE), "compare"),
    (re.compile(r"\b(?:automation|automated)\b", re.IGNORECASE), "automate"),
    (re.compile(r"\b(?:translation|translator)\b", re.IGNORECASE), "translate"),
    (re.compile(r"\b(?:scheduling|scheduler)\b", re.IGNORECASE), "schedule"),
    (re.compile(r"\b(?:monitoring)\b", re.IGNORECASE), "monitor"),
    (re.compile(r"\b(?:reviewer|reviewing)\b", re.IGNORECASE), "review"),
    (re.compile(r"\b(?:extraction|extractor)\b", re.IGNORECASE), "extract"),
    (re.compile(r"\b(?:parsing|parser)\b", re.IGNORECASE), "parse"),
    (re.compile(r"\b(?:evaluation|evaluator)\b", re.IGNORECASE), "evaluate"),
]

EXTRACTED_FIELDS = [
    "platforms",
    "languages",
    "action_types",
    "target_domains",
    "output_formats",
    "metrics",
]


class SkillsIESystem:
    """Rule-based information extraction system for skill descriptions."""

    def __init__(self, config: IEConfig, variant: str = "enhanced") -> None:
        """初始化关键字模式、动作别名模式和指标模式。"""
        self.config = config
        self.variant = variant
        self.use_action_aliases = variant != "baseline"
        self.documents: List[Dict[str, Any]] = []
        self.extraction_results: List[Dict[str, Any]] = []

        self._platform_patterns = self._build_keyword_patterns(config.platform_keywords)
        self._language_patterns = self._build_keyword_patterns(config.language_keywords)
        self._action_patterns = self._build_keyword_patterns(config.action_keywords)
        self._domain_patterns = self._build_keyword_patterns(config.domain_keywords)
        self._format_patterns = self._build_keyword_patterns(config.output_format_keywords)
        self._metric_patterns = [
            re.compile(
                r"(\d+)[\-\s]*(signal|criteria|item|point|step|dimension|layer|level|module|metric|check|rule|test|factor)",
                re.IGNORECASE,
            ),
            re.compile(r"(?:across|over|with|covering|spanning)\s+(\d+)\s+([\w\-]+)", re.IGNORECASE),
            re.compile(r"(\d+)\s*[-–—]\s*(\d+)\s*(?:scale|score|range|rating)", re.IGNORECASE),
            re.compile(
                r"(?:supports?|covers?|includes?)\s+(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+([\w\-]+)",
                re.IGNORECASE,
            ),
        ]

    @staticmethod
    def _build_keyword_patterns(keywords: List[str]) -> List[Tuple[re.Pattern[str], str]]:
        """把关键字列表编译成正则模式，供字段抽取复用。"""
        patterns: List[Tuple[re.Pattern[str], str]] = []
        for keyword in keywords:
            escaped = re.escape(keyword)
            patterns.append((re.compile(r"\b" + escaped + r"\b", re.IGNORECASE), keyword.lower()))
        return patterns

    @staticmethod
    def _empty_extraction() -> Dict[str, Any]:
        """构造一个字段齐全但内容为空的抽取结果骨架。"""
        extraction = {field: [] for field in EXTRACTED_FIELDS}
        extraction["evidence"] = {field: [] for field in EXTRACTED_FIELDS}
        return extraction

    @staticmethod
    def _build_evidence_entry(
        field: str,
        value: Any,
        rule_source: str,
        pattern_source: str,
        matched_text: str,
        context: str,
        extra: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """生成统一结构的证据记录。"""
        entry: Dict[str, Any] = {
            "field": field,
            "value": value,
            "rule_source": rule_source,
            "pattern_source": pattern_source,
            "matched_text": matched_text,
            "context": context,
        }
        if extra:
            entry.update(extra)
        return entry

    @staticmethod
    def _context_snippet(text: str, start: int, end: int, window: int = 48) -> str:
        """截取命中片段周边的上下文，提升可解释性。"""
        left = max(0, start - window)
        right = min(len(text), end + window)
        snippet = " ".join(text[left:right].split())
        if left > 0:
            snippet = f"…{snippet}"
        if right < len(text):
            snippet = f"{snippet}…"
        return snippet

    @staticmethod
    def _short_text(value: str, limit: int = 220) -> str:
        """生成适合报告展示的短文本预览。"""
        value = " ".join(value.split())
        if len(value) <= limit:
            return value
        return value[: limit - 1] + "…"

    def load_data(self) -> int:
        """加载共享技能数据集。"""
        with self.config.paths.data_file.open("r", encoding="utf-8") as file:
            self.documents = json.load(file)
        return len(self.documents)

    def _read_external_skill_text(self, doc: Dict[str, Any]) -> str:
        """优先读取外部 skill_md 文本文件，获取更完整的抽取语料。"""
        data_dir = self.config.paths.data_file.parent
        raw_path = str(doc.get("skill_md_raw_text_path") or "").strip()
        text_path = str(doc.get("skill_md_text_path") or "").strip()

        for rel_path in [raw_path, text_path]:
            if not rel_path:
                continue
            path = data_dir / rel_path
            if path.exists():
                try:
                    return path.read_text(encoding="utf-8")
                except OSError:
                    continue
        return ""

    def extract_from_text(self, text: str) -> Dict[str, Any]:
        """按当前实例默认变体执行抽取。"""
        return self._extract_structured(text, use_action_aliases=self.use_action_aliases)

    def extract_from_text_variant(self, text: str, variant: str = "enhanced") -> Dict[str, Any]:
        """按指定变体执行抽取。"""
        return self._extract_structured(text, use_action_aliases=(variant != "baseline"))

    def extract_debug_payload(self, text: str, variant: str = "enhanced") -> Dict[str, Any]:
        """返回包含证据和摘要的调试结构。"""
        extraction = self.extract_from_text_variant(text, variant=variant)
        evidence_map = extraction.get("evidence", {}) if isinstance(extraction, dict) else {}
        evidence_count = 0
        if isinstance(evidence_map, dict):
            evidence_count = sum(len(items or []) for items in evidence_map.values())
        nonempty_fields = [
            field
            for field in ["platforms", "languages", "action_types", "target_domains", "output_formats", "metrics"]
            if extraction.get(field, [])
        ]
        return {
            "variant": variant,
            "input_text": text,
            "extraction": extraction,
            "evidence": evidence_map,
            "evidence_count": evidence_count,
            "summary": {
                "nonempty_fields": nonempty_fields,
                "info_point_count": len(nonempty_fields),
            },
        }

    def _extract_structured(self, text: str, use_action_aliases: bool) -> Dict[str, Any]:
        """执行完整的结构化抽取流程。"""
        if not text:
            return self._empty_extraction()

        extraction = self._empty_extraction()
        evidence = extraction["evidence"]

        # 每个字段都同时生成“值”和“证据”，后续可以直接用于解释与评测。
        extraction["platforms"], evidence["platforms"] = self._extract_keywords_with_evidence(
            text, self._platform_patterns, field="platforms", rule_source="exact_keyword"
        )
        extraction["languages"], evidence["languages"] = self._extract_keywords_with_evidence(
            text, self._language_patterns, field="languages", rule_source="exact_keyword"
        )
        action_values, action_evidence = self._extract_keywords_with_evidence(
            text, self._action_patterns, field="action_types", rule_source="exact_keyword"
        )
        if use_action_aliases:
            action_values, alias_evidence = self._expand_action_aliases_with_evidence(text, action_values)
            action_evidence.extend(alias_evidence)
        extraction["action_types"] = action_values
        evidence["action_types"] = action_evidence
        extraction["target_domains"], evidence["target_domains"] = self._extract_keywords_with_evidence(
            text, self._domain_patterns, field="target_domains", rule_source="exact_keyword"
        )
        extraction["output_formats"], evidence["output_formats"] = self._extract_keywords_with_evidence(
            text, self._format_patterns, field="output_formats", rule_source="exact_keyword"
        )
        extraction["metrics"], evidence["metrics"] = self._extract_metrics_with_evidence(text)
        return extraction

    def _extract_keywords(self, text: str, patterns: List[Tuple[re.Pattern[str], str]]) -> List[str]:
        """仅提取命中的关键字值，不保留证据。"""
        seen = set()
        values: List[str] = []
        for pattern, keyword in patterns:
            if pattern.search(text) and keyword not in seen:
                seen.add(keyword)
                values.append(keyword)
        return values

    def _extract_keywords_with_evidence(
        self,
        text: str,
        patterns: List[Tuple[re.Pattern[str], str]],
        field: str,
        rule_source: str,
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """提取关键字并记录每次命中的证据。"""
        seen = set()
        values: List[str] = []
        evidence: List[Dict[str, Any]] = []
        for pattern, keyword in patterns:
            for match in pattern.finditer(text):
                if keyword not in seen:
                    seen.add(keyword)
                    values.append(keyword)
                matched_text = match.group(0).strip()
                evidence.append(
                    self._build_evidence_entry(
                        field=field,
                        value=keyword,
                        rule_source=rule_source,
                        pattern_source=pattern.pattern,
                        matched_text=matched_text,
                        context=self._context_snippet(text, match.start(), match.end()),
                    )
                )
        return values, evidence

    def _expand_action_aliases(self, text: str, action_types: List[str]) -> List[str]:
        """通过动作别名模式补充动作类型。"""
        seen = set(action_types)
        expanded = list(action_types)
        for pattern, canonical_action in ACTION_ALIAS_PATTERNS:
            if pattern.search(text) and canonical_action not in seen:
                seen.add(canonical_action)
                expanded.append(canonical_action)
        return expanded

    def _expand_action_aliases_with_evidence(
        self, text: str, action_types: List[str]
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        """补充动作别名，并把别名命中纳入证据。"""
        seen = set(action_types)
        expanded = list(action_types)
        evidence: List[Dict[str, Any]] = []
        for pattern, canonical_action in ACTION_ALIAS_PATTERNS:
            for match in pattern.finditer(text):
                if canonical_action not in seen:
                    seen.add(canonical_action)
                    expanded.append(canonical_action)
                matched_text = match.group(0).strip()
                evidence.append(
                    self._build_evidence_entry(
                        field="action_types",
                        value=canonical_action,
                        rule_source="alias_pattern",
                        pattern_source=pattern.pattern,
                        matched_text=matched_text,
                        context=self._context_snippet(text, match.start(), match.end()),
                    )
                )
        return expanded, evidence

    def _extract_metrics(self, text: str) -> List[Dict[str, str]]:
        """仅提取指标项，不返回证据。"""
        metrics, _ = self._extract_metrics_with_evidence(text)
        return metrics

    def _extract_metrics_with_evidence(
        self, text: str
    ) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
        """通过正则模式抽取数值/量纲型指标，并记录证据。"""
        word_to_num = {
            "two": "2",
            "three": "3",
            "four": "4",
            "five": "5",
            "six": "6",
            "seven": "7",
            "eight": "8",
            "nine": "9",
            "ten": "10",
            "eleven": "11",
            "twelve": "12",
        }
        metrics: List[Dict[str, str]] = []
        evidence: List[Dict[str, Any]] = []
        seen = set()

        for pattern in self._metric_patterns:
            for match in pattern.finditer(text):
                groups = match.groups()
                if len(groups) < 2:
                    continue
                value = groups[0]
                unit = groups[1]
                if value.lower() in word_to_num:
                    value = word_to_num[value.lower()]
                key = f"{value}-{unit.lower()}"
                if key in seen:
                    continue
                seen.add(key)
                matched_text = match.group(0).strip()
                metric_item = {
                    "value": value,
                    "unit": unit.lower(),
                    "context": matched_text,
                    "field": "metrics",
                    "rule_source": "metric_regex",
                    "pattern_source": pattern.pattern,
                    "matched_text": matched_text,
                }
                metrics.append(metric_item)
                evidence.append(dict(metric_item))
        return metrics, evidence

    def build_event_records(self, variant: str = "enhanced") -> List[Dict[str, Any]]:
        """把原始文档集转换为评测和比较使用的事件记录。"""
        if not self.documents:
            self.load_data()

        events: List[Dict[str, Any]] = []
        for doc in self.documents:
            skill_id = doc.get("skill_id", "")
            skill_name = doc.get("skill_name", "")
            description = doc.get("description", "")
            external_skill_text = self._read_external_skill_text(doc)
            skill_md_raw_text = doc.get("skill_md_raw_text", "")
            skill_md = doc.get("skill_md", "")
            category = doc.get("category", "")
            # 优先选择更长、更原始的 skill_md 文本，以提升规则覆盖率。
            extraction_text = external_skill_text or skill_md_raw_text or skill_md or description or ""
            full_text = f"{skill_name} {category} {extraction_text}"
            extraction = self.extract_from_text_variant(full_text, variant=variant)
            event = {
                "skill_id": skill_id,
                "skill_name": skill_name,
                "owner": doc.get("owner", ""),
                "category": category,
                "detail_url": doc.get("detail_url", ""),
                "description_preview": self._short_text(description, 200) if description else "",
                "variant": variant,
                "evidence_count": sum(
                    len(items or [])
                    for items in extraction.get("evidence", {}).values()
                ),
                "extraction": extraction,
                "event_summary": self._build_event_summary(skill_name, extraction),
                "info_point_count": sum(
                    1 for field in ["platforms", "languages", "action_types", "target_domains", "output_formats", "metrics"]
                    if extraction.get(field, [])
                ),
            }
            events.append(event)
        return events

    def extract_all(self) -> List[Dict[str, Any]]:
        """对当前数据集执行整批抽取，并缓存结果。"""
        if not self.documents:
            self.load_data()

        self.extraction_results = []
        for doc in self.documents:
            skill_id = doc.get("skill_id", "")
            skill_name = doc.get("skill_name", "")
            description = doc.get("description", "")
            external_skill_text = self._read_external_skill_text(doc)
            skill_md_raw_text = doc.get("skill_md_raw_text", "")
            skill_md = doc.get("skill_md", "")
            category = doc.get("category", "")
            extraction_text = external_skill_text or skill_md_raw_text or skill_md or description or ""
            full_text = f"{skill_name} {category} {extraction_text}"
            extraction = self.extract_from_text(full_text)
            event = {
                "skill_id": skill_id,
                "skill_name": skill_name,
                "owner": doc.get("owner", ""),
                "category": category,
                "detail_url": doc.get("detail_url", ""),
                "description_preview": self._short_text(description, 200) if description else "",
                "variant": self.variant,
                "evidence_count": sum(
                    len(items or [])
                    for items in extraction.get("evidence", {}).values()
                ),
                "extraction": extraction,
                "event_summary": self._build_event_summary(skill_name, extraction),
                "info_point_count": sum(
                    1 for field in ["platforms", "languages", "action_types", "target_domains", "output_formats", "metrics"]
                    if extraction.get(field, [])
                ),
            }
            self.extraction_results.append(event)
        return self.extraction_results

    @staticmethod
    def _build_event_summary(skill_name: str, extraction: Dict[str, Any]) -> str:
        """把抽取结果压缩为一段便于阅读的摘要。"""
        parts = [f"[{skill_name}]"]

        actions = extraction.get("action_types", [])
        if actions:
            parts.append(f"能够 {'/'.join(actions[:3])}")

        domains = extraction.get("target_domains", [])
        if domains:
            parts.append(f"服务于 {'/'.join(domains[:2])} 领域")

        platforms = extraction.get("platforms", [])
        if platforms:
            parts.append(f"支持 {'/'.join(platforms[:3])} 平台")

        languages = extraction.get("languages", [])
        if languages:
            parts.append(f"使用 {'/'.join(languages[:3])} 技术")

        formats = extraction.get("output_formats", [])
        if formats:
            parts.append(f"输出 {'/'.join(formats[:2])} 格式")

        metrics = extraction.get("metrics", [])
        if metrics:
            metric_strs = [f"{m['value']}{m['unit']}" for m in metrics[:2]]
            parts.append(f"涉及 {', '.join(metric_strs)}")

        return "，".join(parts) + "。"

    @staticmethod
    def _compact_evidence_sample(event: Dict[str, Any], evidence_entry: Dict[str, Any]) -> Dict[str, Any]:
        """把完整证据记录压缩成报告友好的样本结构。"""
        return {
            "skill_name": event.get("skill_name", ""),
            "skill_id": event.get("skill_id", ""),
            "field": evidence_entry.get("field", ""),
            "value": evidence_entry.get("value", ""),
            "rule_source": evidence_entry.get("rule_source", ""),
            "pattern_source": evidence_entry.get("pattern_source", ""),
            "matched_text": evidence_entry.get("matched_text", ""),
            "context": evidence_entry.get("context", ""),
        }

    def _summarize_explainability(self) -> Dict[str, Any]:
        """按字段汇总证据覆盖率和证据来源分布。"""
        total = len(self.extraction_results)
        field_docs = Counter()
        field_items = Counter()
        field_sources: Dict[str, Counter] = defaultdict(Counter)
        field_samples: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        global_sources = Counter()

        for event in self.extraction_results:
            extraction = event.get("extraction", {})
            evidence_map = extraction.get("evidence", {}) if isinstance(extraction, dict) else {}
            for field in EXTRACTED_FIELDS:
                items = evidence_map.get(field, []) or []
                if not items:
                    continue
                field_docs[field] += 1
                field_items[field] += len(items)
                for item in items:
                    source = item.get("rule_source") or item.get("pattern_source") or "unknown"
                    field_sources[field][source] += 1
                    global_sources[source] += 1
                if len(field_samples[field]) < 2:
                    field_samples[field].append(self._compact_evidence_sample(event, items[0]))

        field_summary: Dict[str, Any] = {}
        for field in EXTRACTED_FIELDS:
            docs_with_evidence = field_docs.get(field, 0)
            evidence_count = field_items.get(field, 0)
            field_summary[field] = {
                "documents_with_evidence": docs_with_evidence,
                "coverage_rate": round(docs_with_evidence / max(total, 1), 4),
                "evidence_items": evidence_count,
                "evidence_per_document": round(evidence_count / max(docs_with_evidence, 1), 4)
                if docs_with_evidence
                else 0.0,
                "top_sources": [
                    {"source": source, "count": count}
                    for source, count in field_sources[field].most_common(5)
                ],
                "samples": field_samples.get(field, []),
            }

        return {
            "total_documents": total,
            "field_summary": field_summary,
            "global_source_distribution": [
                {"source": source, "count": count}
                for source, count in global_sources.most_common()
            ],
        }

    def generate_report(self) -> Dict[str, Any]:
        """生成抽取覆盖率、值分布与证据统计报告。"""
        if not self.extraction_results:
            self.extract_all()

        total = len(self.extraction_results)
        field_counts = Counter()
        field_value_counts: Dict[str, Counter] = defaultdict(Counter)
        info_point_distribution = Counter()

        for event in self.extraction_results:
            extraction = event["extraction"]
            info_point_distribution[event["info_point_count"]] += 1
            for field_name in ["platforms", "languages", "action_types", "target_domains", "output_formats", "metrics"]:
                values = extraction.get(field_name, [])
                if values:
                    field_counts[field_name] += 1
                    for value in values:
                        if isinstance(value, dict):
                            normalized = f"{value.get('value', '')} {value.get('unit', '')}".strip()
                        else:
                            normalized = str(value)
                        field_value_counts[field_name][normalized] += 1

        report = {
            "generated_at": utc_now_iso(),
            "variant": self.variant,
            "total_documents": total,
            "field_extraction_rates": {
                field: {
                    "count": field_counts[field],
                    "rate": round(field_counts[field] / max(total, 1), 4),
                }
                for field in ["platforms", "languages", "action_types", "target_domains", "output_formats", "metrics"]
            },
            "top_values_per_field": {
                field: counter.most_common(15)
                for field, counter in field_value_counts.items()
            },
            "info_point_distribution": dict(sorted(info_point_distribution.items())),
            "documents_with_all_fields": sum(
                1 for e in self.extraction_results if e["info_point_count"] >= 5
            ),
            "documents_with_no_extraction": sum(
                1 for e in self.extraction_results if e["info_point_count"] == 0
            ),
            "total_evidence_items": sum(e.get("evidence_count", 0) for e in self.extraction_results),
            "explainability": self._summarize_explainability(),
        }
        return report

    def save_results(self) -> Dict[str, str]:
        """保存抽取结果、报告与项目状态文件。"""
        self.config.ensure_runtime_dirs()
        results_path = self.config.paths.extraction_results_file
        save_json_atomic(
            results_path,
            {
                "generated_at": utc_now_iso(),
                "variant": self.variant,
                "total": len(self.extraction_results),
                "events": self.extraction_results,
            },
        )

        report = self.generate_report()
        save_json_atomic(self.config.paths.extraction_report_file, report)
        save_json_atomic(
            self.config.paths.project_state_file,
            {
                "last_extraction_at": utc_now_iso(),
                "variant": self.variant,
                "document_count": len(self.documents),
                "extraction_count": len(self.extraction_results),
                "report_path": str(self.config.paths.extraction_report_file),
                "results_path": str(results_path),
            },
        )
        return {
            "results_file": str(results_path),
            "report_file": str(self.config.paths.extraction_report_file),
            "state_file": str(self.config.paths.project_state_file),
        }

    def search_extractions(
        self, query: str, field: str | None = None, top_k: int = 10
    ) -> List[Dict[str, Any]]:
        """在抽取结果上做轻量字段检索。"""
        if not self.extraction_results:
            self.extract_all()

        # 这里使用启发式打分而非复杂排序，目标是便于人工浏览抽取结果。
        query_lower = query.lower().strip()
        scored: List[Tuple[float, Dict[str, Any]]] = []
        fields_to_search = [field] if field else [
            "platforms",
            "languages",
            "action_types",
            "target_domains",
            "output_formats",
        ]

        for event in self.extraction_results:
            extraction = event["extraction"]
            score = 0.0

            for f in fields_to_search:
                values = extraction.get(f, [])
                for value in values:
                    value_text = str(value).lower()
                    if query_lower == value_text:
                        score += 3.0
                    elif query_lower in value_text:
                        score += 1.5
                    elif value_text in query_lower:
                        score += 1.0

            skill_name = str(event.get("skill_name") or "")
            category = str(event.get("category") or "")
            if query_lower in skill_name.lower():
                score += 2.0
            if query_lower in category.lower():
                score += 1.0

            if score > 0:
                scored.append((score, event))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [{**event, "match_score": score} for score, event in scored[:top_k]]


def print_extraction_results(results: List[Dict[str, Any]], limit: int = 10) -> None:
    """把抽取结果打印为终端可读格式。"""
    for i, event in enumerate(results[:limit], 1):
        print(f"\n[{i}] {event['skill_name']}  (category: {event.get('category', '')})")
        extraction = event["extraction"]
        if extraction["platforms"]:
            print(f"    平台: {', '.join(extraction['platforms'])}")
        if extraction["languages"]:
            print(f"    技术: {', '.join(extraction['languages'])}")
        if extraction["action_types"]:
            print(f"    功能: {', '.join(extraction['action_types'])}")
        if extraction["target_domains"]:
            print(f"    领域: {', '.join(extraction['target_domains'])}")
        if extraction["output_formats"]:
            print(f"    格式: {', '.join(extraction['output_formats'])}")
        if extraction["metrics"]:
            metrics_str = ", ".join(f"{m['value']} {m['unit']}" for m in extraction["metrics"])
            print(f"    指标: {metrics_str}")

        evidence_map = extraction.get("evidence", {})
        evidence_lines: List[str] = []
        if isinstance(evidence_map, dict):
            for field_name in EXTRACTED_FIELDS:
                field_evidence = evidence_map.get(field_name, []) or []
                if not field_evidence:
                    continue
                sample = field_evidence[0]
                source = sample.get("rule_source") or sample.get("pattern_source") or "unknown"
                matched_text = sample.get("matched_text") or sample.get("context") or ""
                value = sample.get("value", "")
                evidence_lines.append(f"{field_name}:{source} -> {value} | {matched_text}")
                if len(evidence_lines) >= 2:
                    break
        if evidence_lines:
            print(f"    证据: {' ; '.join(evidence_lines)}")
        print(f"    事件: {event.get('event_summary', '')}")
        if "match_score" in event:
            print(f"    匹配分: {event['match_score']:.2f}")
