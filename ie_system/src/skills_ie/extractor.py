"""
结构化信息抽取引擎 —— IE 子系统的核心。

从技能描述文本中自动抽取 6 个结构化字段：
  platforms      — 支持的平台/工具（如 github, slack, google）
  languages      — 使用的编程语言/框架（如 python, react, pytorch）
  action_types   — 执行的动作类型（如 analyze, generate, monitor）
  target_domains — 面向的应用领域（如 e-commerce, ai, seo）
  output_formats — 输出格式（如 json, pdf, markdown）
  metrics        — 量化指标（如 "5 criteria", "10-point scale"）

支持的抽取变体：
  baseline  — 纯规则引擎：关键词精确匹配 + metrics 正则
  enhanced  — 规则 + GLiNER 联合：GLiNER NER 模型先抽取实体，规则作为回退和补充

架构概览：
  1. 文本准备（_prepare_document_inputs）:
     - 拼接 skill_name + description + external skill text
     - 判断英语主导性（english_dominant），决定是否启用 GLiNER
  
  2. 抽取流程（_extract_structured_enhanced）:
     - GLiNER 阶段：GLiNER 模型批量预测实体 → 词汇规范化 → 分类到对应字段
     - 回退阶段：对 GLiNER 未命中的字段，用关键词正则 + 动作别名做补充
     - metrics 单独处理：先用 GLiNER 找到的数字候选再做正则解析
  
  3. 输出（_build_event_from_doc）:
     - 构建含 extraction + evidence + event_summary 的事件记录
     - evidence 记录每条结果来自哪个规则/模型，用于可解释性

关键设计决策：
  - VOCAB_CANONICAL_OVERRIDES：处理缩写到全称的规范化（如 jd → jd.com）
  - ACTION_ALIAS_PATTERNS：将名词形式映射到动词原形（如 analysis → analyze）
  - _normalize_span_candidates：多级匹配策略（精确 → 别名 → 子串 → 模糊编辑距离）
  - english_only_bias：非英文文本跳过 GLiNER（避免模型对中文的误判）
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from .config import IEConfig
from .remote_llm import call_openai_compatible_json
from .state import save_json_atomic, utc_now_iso

# ═══════════════════════════════════════════════════════════════════════
# 动作别名映射（enhanced 变体使用）
# ═══════════════════════════════════════════════════════════════════════
# 将动作的名词/形容词形式规范化到动词原形。
# 例如 description 中含 "analysis" → 抽取 action_types=["analyze"]
# 每个元组是 (匹配正则, 规范化动作名)
# 在 enhanced 变体的回退阶段和 alias 扩展阶段都会使用
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
    (re.compile(r"\b(?:design|designer|designing)\b", re.IGNORECASE), "design"),
    (re.compile(r"\b(?:authentication)\b", re.IGNORECASE), "authenticate"),
    (re.compile(r"\b(?:authorization)\b", re.IGNORECASE), "authorize"),
    (re.compile(r"\b(?:migration|migrations)\b", re.IGNORECASE), "migrate"),
    (re.compile(r"\b(?:refactoring)\b", re.IGNORECASE), "refactor"),
    (re.compile(r"\b(?:synchronization|synchronisation)\b", re.IGNORECASE), "sync"),
]

# ═══════════════════════════════════════════════════════════════════════
# 字段定义
# ═══════════════════════════════════════════════════════════════════════

# 全部 6 个抽取字段（含 metrics）
EXTRACTED_FIELDS = [
    "platforms",
    "languages",
    "action_types",
    "target_domains",
    "output_formats",
    "metrics",
]

# 5 个枚举字段（不含 metrics，metrics 用独立的正则匹配）
# GLiNER 和关键词匹配都针对 ENUM_FIELDS 工作
ENUM_FIELDS = [
    "platforms",
    "languages",
    "action_types",
    "target_domains",
    "output_formats",
]

# 字段名 → 实例属性名的映射
# 用于根据字段名动态获取对应的关键词正则列表
FIELD_PATTERN_ATTRS = {
    "platforms": "_platform_patterns",
    "languages": "_language_patterns",
    "action_types": "_action_patterns",
    "target_domains": "_domain_patterns",
    "output_formats": "_format_patterns",
}

# ═══════════════════════════════════════════════════════════════════════
# 词汇规范化覆盖表
# ═══════════════════════════════════════════════════════════════════════
# 处理缩写/简写 → 全称的映射。
# 例如 "jd" → "jd.com"（防止缩写与其他实体的 JD 混淆）
# 这些覆盖在 _canonicalize_vocab_value 中应用，优先级高于 GLiNER 别名。
VOCAB_CANONICAL_OVERRIDES: Dict[str, Dict[str, str]] = {
    "platforms": {
        "jd": "jd.com",
        "x.com": "twitter",
        "vip": "vip.com",
    },
    "languages": {
        "golang": "go",
        "nextjs": "next.js",
        "nodejs": "node.js",
        "postgres": "postgresql",
    },
    "target_domains": {
        "ecommerce": "e-commerce",
    },
}

GLINER_PLATFORM_BOUNDARY_TO_DOMAIN: Dict[str, str] = {
    "ios": "mobile",
    "android": "mobile",
}

GLINER_PLATFORM_BOUNDARY_FILTER = {
    "macos",
    "linux",
    "windows",
}

GLINER_PLATFORM_OUT_OF_SCHEMA = {
    "mcp",
    "claude",
    "claude code",
    "gemini",
    "chatgpt",
    "perplexity",
    "codex",
    "chrome",
    "prisma",
}

GLINER_LANGUAGE_OUT_OF_SCHEMA = {
    "llm",
}

GLINER_GENERIC_ACTION_NOUNS = {
    "actions",
    "advanced patterns",
    "autonomy",
    "actionability",
    "cookie management",
    "crawlability",
    "data loading",
    "error handling",
    "form filling",
    "interactions",
    "navigation",
    "payments",
    "pre-built actions",
    "pretooluse",
    "queries",
    "rate limiting",
    "reactivity",
    "resource management",
    "server actions",
    "skill loading",
    "state management",
    "voice cloning",
}

GLINER_GENERIC_OUTPUT_META = {
    "output format",
    "coverage",
    "field-level",
    "minimal",
    "quick chat display",
    "visual-style.md",
    "design.md",
    "stdin",
    "br",
    "string",
    "urls",
}


# ═══════════════════════════════════════════════════════════════════════
# SkillsIESystem — 核心信息抽取引擎
# ═══════════════════════════════════════════════════════════════════════

class SkillsIESystem:
    """
    信息抽取系统 —— 支持规则 baseline 和 GLiNER 增强 enhanced 两种变体。
    
    初始化时预编译所有关键词正则、构建词汇规范化目录、配置 GLiNER 参数。
    主要 API:
      load_data()           — 加载数据集
      extract_all()         — 全量抽取，结果存入 self.extraction_results
      extract_debug_payload(text) — 抽取单条文本并返回完整调试信息
      search_extractions(query)   — 搜索已抽取结果
      generate_report()     — 生成字段覆盖率统计报告
      save_results()        — 保存结果 + 报告 + 状态文件
    
    内部方法分为多个层次：
      (a) 文本预处理 —— _build_text_bundle, _prepare_focus_text, _read_external_skill_text
      (b) 规则匹配    —— _extract_keywords_with_evidence, _extract_metrics_with_evidence
      (c) GLiNER 集成 —— _ensure_gliner_model, _predict_gliner_batch, _project_gliner_predictions
      (d) 词汇规范化  —— _normalize_to_vocab, _normalize_span_candidates, _initialize_normalization_catalogs
      (e) 组装与输出  —— _extract_structured_enhanced, _build_event_from_doc, generate_report
    """

    def __init__(self, config: IEConfig, variant: str = "enhanced") -> None:
        self.config = config
        self.variant = variant
        # baseline 变体不使用动作别名扩展（保持纯关键词匹配）
        self.use_action_aliases = variant != "baseline"
        self.documents: List[Dict[str, Any]] = []
        self.extraction_results: List[Dict[str, Any]] = []

        # ── 预编译所有关键词正则 ──
        #  对 ie_config.json 中的 keywords 数组，逐词编译为 \bkeyword\b 形式的正则。\b 单词边界保证 "java" 不会误匹配到 "javascript"。
        self._platform_patterns = self._build_keyword_patterns(config.platform_keywords)
        self._language_patterns = self._build_keyword_patterns(config.language_keywords)
        self._action_patterns = self._build_keyword_patterns(config.action_keywords)
        self._domain_patterns = self._build_keyword_patterns(config.domain_keywords)
        self._format_patterns = self._build_keyword_patterns(config.output_format_keywords)

        # ── 预编译 metrics 正则 ──
        # metrics 不依赖关键词列表，而是用正则从文本中直接匹配 "数字+单位" 模式
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

        # ── 词汇规范化目录 ──
        # _field_vocabs: 每个字段的关键词列表（来自配置）
        # exact_map: cleaned_keyword → canonical（如 lowercase）
        # folded_map: 去除特殊字符后的 key → canonical（如 "node.js" → "nodejs" → "node.js"）
        # alias_map: 别名 → canonical（如 "github.com" → "github"）
        # allowed_values: 该字段所有合法规范值集合
        self._field_vocabs = {
            "platforms": config.platform_keywords,
            "languages": config.language_keywords,
            "action_types": config.action_keywords,
            "target_domains": config.domain_keywords,
            "output_formats": config.output_format_keywords,
        }
        # 直接匹配
        self._field_exact_maps: Dict[str, Dict[str, str]] = {}
        # 大小字符更改之后匹配
        self._field_folded_maps: Dict[str, Dict[str, str]] = {}
        # 别名匹配，比如github.com -> github
        self._field_alias_maps: Dict[str, Dict[str, str]] = {}
        # 距离 <= 2 的fuzzy匹配，比如githu -> github，这个匹配只有在字符串长度大于或等于5的时候才会启用
        # 避免出现距离匹配过于激进，比如将go匹配到任何go之外的东西
        self._field_allowed_values: Dict[str, set[str]] = {}
        self._field_folded_allowed_values: Dict[str, Dict[str, str]] = {}
        # 为每个字段构建 5 个查找结构
        self._initialize_normalization_catalogs()

        # ── GLiNER 初始化 ──
        # label_to_field: GLiNER 标签 → IE 字段映射（来自配置的 label_map）
        # gliner_labels: GLiNER 推理时使用的全部标签列表
        # gliner_thresholds: 每个字段的置信度阈值
        # gliner_min_threshold: _gliner_min_threshold 是用来传给 GLiNER API 的，低于这个值的预测 GLiNER 直接不会返回
        self._label_to_field = {
            label.lower(): field for label, field in self.config.gliner.label_map.items()
        }
        self._gliner_labels = list(self.config.gliner.label_map.keys())
        self._gliner_thresholds = dict(self.config.gliner.field_thresholds)
        self._gliner_min_threshold = min(self._gliner_thresholds.values() or [0.0])
        self._gliner_model: Any | None = None
        self._gliner_checked = False
        self._gliner_load_error: str | None = None

    # ────────────────────────────────────────────────────────────────
    # (A) 关键词正则构建
    # ────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_keyword_patterns(keywords: Sequence[str]) -> List[Tuple[re.Pattern[str], str]]:
        patterns: List[Tuple[re.Pattern[str], str]] = []
        for keyword in keywords:
            escaped = re.escape(keyword)
            patterns.append((re.compile(r"\b" + escaped + r"\b", re.IGNORECASE), keyword.lower()))
        return patterns

    # ────────────────────────────────────────────────────────────────
    # (B) 词汇规范化目录与规范化工具
    # ────────────────────────────────────────────────────────────────

    def _initialize_normalization_catalogs(self) -> None:
        for field, keywords in self._field_vocabs.items():
            exact_map: Dict[str, str] = {}
            folded_map: Dict[str, str] = {}
            allowed_values: set[str] = set()

            for keyword in keywords:
                canonical = self._canonicalize_vocab_value(field, keyword)
                clean_keyword = self._normalize_surface(keyword)
                exact_map[clean_keyword] = canonical
                folded_map[self._fold_lookup(clean_keyword)] = canonical
                clean_canonical = self._normalize_surface(canonical)
                exact_map[clean_canonical] = canonical
                folded_map[self._fold_lookup(clean_canonical)] = canonical
                allowed_values.add(canonical)

            alias_map: Dict[str, str] = {}
            for alias, canonical in self.config.gliner.aliases.get(field, {}).items():
                clean_alias = self._normalize_surface(alias)
                alias_map[clean_alias] = canonical
                alias_map[self._fold_lookup(clean_alias)] = canonical
                allowed_values.add(canonical)
                clean_canonical = self._normalize_surface(canonical)
                exact_map.setdefault(clean_canonical, canonical)
                folded_map.setdefault(self._fold_lookup(clean_canonical), canonical)

            self._field_exact_maps[field] = exact_map
            self._field_folded_maps[field] = folded_map
            self._field_alias_maps[field] = alias_map
            self._field_allowed_values[field] = allowed_values
            self._field_folded_allowed_values[field] = {
                self._fold_lookup(value): value for value in allowed_values
            }

    def _canonicalize_vocab_value(self, field: str, value: str) -> str:
        clean_value = self._normalize_surface(value)
        return VOCAB_CANONICAL_OVERRIDES.get(field, {}).get(clean_value, clean_value)

    @staticmethod
    def _empty_extraction() -> Dict[str, Any]:
        """构建空的抽取结果模板，每个字段都是空列表，evidence 同理。"""
        extraction = {field: [] for field in EXTRACTED_FIELDS}
        extraction["evidence"] = {field: [] for field in EXTRACTED_FIELDS}
        return extraction

    def _build_api_debug_stub(self, reason: str = "disabled") -> Dict[str, Any]:
        remote = self.config.remote_llm
        return {
            "enabled": remote.enabled,
            "available": remote.enabled,
            "used": False,
            "mode": reason,
            "provider": remote.provider,
            "api_base": remote.api_base,
            "model_name": remote.model,
            "normalized_hits": {field: [] for field in EXTRACTED_FIELDS},
            "fallback": {
                field: {"reason": reason, "used": False, "result_count": 0}
                for field in EXTRACTED_FIELDS
            },
            "raw_response": None,
            "model_error": None,
        }
    # 先标准化表面形式，再查覆盖表。例如 "JD" → lowercase → "jd" → override → "jd.com"。

    # ────────────────────────────────────────────────────────────────
    # (C) Evidence 与文本工具方法
    # ────────────────────────────────────────────────────────────────

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
        left = max(0, start - window)
        right = min(len(text), end + window)
        snippet = " ".join(text[left:right].split())
        if left > 0:
            snippet = f"...{snippet}"
        if right < len(text):
            snippet = f"{snippet}..."
        return snippet

    @staticmethod
    def _short_text(value: str, limit: int = 220) -> str:
        value = " ".join(value.split())
        if len(value) <= limit:
            return value
        return value[: limit - 3] + "..."

    @staticmethod
    def _normalize_whitespace(value: str) -> str:
        return " ".join((value or "").split())

    # "Hello World's BEST—Python！"
    @staticmethod
    def _normalize_surface(value: str) -> str:
        value = (value or "").lower()
        # "hello world's best—python！"
        value = value.translate(
            str.maketrans(
                {
                    "’": "'",
                    "‘": "'",
                    "“": '"',
                    "”": '"',
                    "–": "-",
                    "—": "-",
                    "／": "/",
                    "，": ",",
                    "。": ".",
                    "：": ":",
                    "；": ";",
                    "（": "(",
                    "）": ")",
                }
            )
        )
        # "hello world's best-python!"
        value = re.sub(r"\s+", " ", value).strip()
        # "hello world's best-python!"
        return value.strip(" \t\r\n.,;:!?()[]{}<>\"'")
        # "hello world's best-python"

    @classmethod
    def _fold_lookup(cls, value: str) -> str:
        clean_value = cls._normalize_surface(value)
        clean_value = clean_value.replace("&", "and")
        return re.sub(r"[^a-z0-9+#]+", "", clean_value)
    # 去掉所有非字母数字字符

    @staticmethod
    def _dedupe_preserve_order(values: Iterable[Any]) -> List[Any]:
        seen: set[str] = set()
        deduped: List[Any] = []
        for value in values:
            key = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, dict) else str(value)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(value)
        return deduped

    @staticmethod
    def _count_cjk(text: str) -> int:
        return len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))

    @staticmethod
    def _count_ascii_alpha(text: str) -> int:
        return len(re.findall(r"[A-Za-z]", text))

    def _is_english_dominant(self, text: str) -> bool:
        ascii_letters = self._count_ascii_alpha(text)
        cjk_chars = self._count_cjk(text)
        if ascii_letters == 0 and cjk_chars == 0:
            return True
        if cjk_chars == 0:
            return True
        return ascii_letters >= cjk_chars * 1.5

    # ────────────────────────────────────────────────────────────────
    # (D) 数据加载与文本准备
    # ────────────────────────────────────────────────────────────────

    def load_data(self) -> int:
        with self.config.paths.data_file.open("r", encoding="utf-8") as file:
            self.documents = json.load(file)
        return len(self.documents)

    def _read_external_skill_text(self, doc: Dict[str, Any]) -> str:
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

    # GLiNER 模型输入有长度限制，所以要构造一个聚焦文本
    def _prepare_focus_text(
        self,
        skill_name: str,
        category: str,
        description: str,
        extraction_text: str,
    ) -> str:
        skill_name = self._normalize_whitespace(skill_name)
        category = self._normalize_whitespace(category)
        description = self._normalize_whitespace(description)
        extraction_text = self._normalize_whitespace(extraction_text)

        parts = [part for part in [skill_name, category, description] if part]
        focus_text = " ".join(parts)
        if len(description.split()) < 40 and extraction_text:
            head = extraction_text[:1400]
            if description and head.lower().startswith(description.lower()[:80]):
                pass
            else:
                focus_text = " ".join(part for part in [focus_text, head] if part)
        return focus_text or extraction_text or description or skill_name

    def _build_text_bundle(
        self,
        skill_name: str,
        category: str,
        description: str,
        extraction_text: str,
    ) -> Dict[str, Any]:
        full_text = self._normalize_whitespace(
            " ".join(part for part in [skill_name, category, extraction_text] if part)
        )
        focus_text = self._prepare_focus_text(skill_name, category, description, extraction_text)
        english_dominant = self._is_english_dominant(full_text or focus_text)
        fallback_text = focus_text if english_dominant and focus_text else full_text
        gliner_eligible = (
            self.config.gliner.enabled
            and (not self.config.gliner.english_only_bias or english_dominant)
            and bool(focus_text)
        )
        return {
            "full_text": full_text,
            "gliner_text": focus_text or full_text,
            "fallback_text": fallback_text or full_text,
            "english_dominant": english_dominant,
            "gliner_eligible": gliner_eligible,
        }

    # ────────────────────────────────────────────────────────────────
    # (E) 抽取入口（extract / extract-one / extract_debug_payload）
    # ────────────────────────────────────────────────────────────────

    def extract_from_text(self, text: str) -> Dict[str, Any]:
        return self.extract_from_text_variant(text, variant=self.variant)

    def extract_from_text_variant(self, text: str, variant: str = "enhanced") -> Dict[str, Any]:
        extraction, _ = self._extract_text_variant(text, variant=variant, collect_debug=False)
        return extraction

    def extract_debug_payload(self, text: str, variant: str = "enhanced") -> Dict[str, Any]:
        extraction, debug_payload = self._extract_text_variant(text, variant=variant, collect_debug=True)
        evidence_map = extraction.get("evidence", {}) if isinstance(extraction, dict) else {}
        evidence_count = 0
        if isinstance(evidence_map, dict):
            evidence_count = sum(len(items or []) for items in evidence_map.values())
        nonempty_fields = [field for field in EXTRACTED_FIELDS if extraction.get(field, [])]
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
            "gliner": debug_payload,
        }

    def _extract_text_variant(
        self,
        text: str,
        variant: str,
        collect_debug: bool,
    ) -> Tuple[Dict[str, Any], Dict[str, Any] | None]:
        if not text:
            return self._empty_extraction(), self._build_gliner_debug_stub({}, reason="empty_text")

        if variant == "baseline":
            extraction = self._extract_structured_baseline(text, use_action_aliases=False)
            return extraction, self._build_gliner_debug_stub({}, reason="baseline_variant")

        if variant == "api":
            extraction, debug_payload = self._extract_structured_api(text)
            if not collect_debug:
                return extraction, None
            return extraction, debug_payload

        bundle = self._build_text_bundle("", "", text, text)
        gliner_predictions: List[Dict[str, Any]] | None = None
        if bundle["gliner_eligible"]:
            gliner_predictions = self._predict_gliner_single(bundle["gliner_text"])
        extraction, debug_payload = self._extract_structured_enhanced(
            bundle=bundle,
            gliner_predictions=gliner_predictions,
            collect_debug=collect_debug,
        )
        return extraction, debug_payload

    def _normalize_llm_enum_values(self, values: Any, field: str) -> List[str]:
        if not isinstance(values, list):
            return []
        normalized_values: List[str] = []
        for item in values:
            candidate = str(item).strip()
            if not candidate:
                continue
            normalized, _ = self._normalize_to_vocab(candidate, field)
            if normalized:
                normalized_values.append(normalized)
        return self._dedupe_preserve_order(normalized_values)

    @staticmethod
    def _normalize_llm_metric_values(values: Any) -> List[Dict[str, str]]:
        if not isinstance(values, list):
            return []
        normalized: List[Dict[str, str]] = []
        for item in values:
            if isinstance(item, dict):
                value = str(item.get("value", "")).strip()
                unit = str(item.get("unit", "")).strip()
            else:
                value = str(item).strip()
                unit = ""
            if not value:
                continue
            normalized.append({"value": value, "unit": unit})
        deduped: List[Dict[str, str]] = []
        seen: set[str] = set()
        for item in normalized:
            key = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _extract_llm_evidence_items(
        self,
        text: str,
        field: str,
        items: Any,
        metrics_mode: bool = False,
    ) -> List[Dict[str, Any]]:
        if not isinstance(items, list):
            return []
        evidence: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            value = item.get("value", "")
            unit = item.get("unit", "") if metrics_mode else ""
            quote = str(item.get("quote", "")).strip()
            if metrics_mode:
                normalized_value = {"value": str(value).strip(), "unit": str(unit).strip()}
                if not normalized_value["value"]:
                    continue
            else:
                normalized_value_text, _ = self._normalize_to_vocab(str(value).strip(), field)
                if not normalized_value_text:
                    continue
                normalized_value = normalized_value_text

            matched_text = quote or str(value).strip()
            text_lower = text.lower()
            matched_lower = matched_text.lower()
            start = text_lower.find(matched_lower) if matched_text else -1
            end = start + len(matched_text) if start >= 0 else -1
            context = self._context_snippet(text, start, end) if start >= 0 else self._short_text(text, 180)
            evidence.append(
                self._build_evidence_entry(
                    field=field,
                    value=normalized_value,
                    rule_source="remote_llm",
                    pattern_source="remote_llm_json",
                    matched_text=matched_text,
                    context=context,
                )
            )
        return evidence

    def _build_llm_prompt(self, text: str) -> str:
        template = self.config.remote_llm.prompt_template
        schema_hints = ""
        if self.config.remote_llm.include_schema_hints:
            schema_hints = (
                "\nAllowed canonical values hints:\n"
                f"- platforms: {', '.join(self.config.platform_keywords[:80])}\n"
                f"- languages: {', '.join(self.config.language_keywords[:80])}\n"
                f"- action_types: {', '.join(self.config.action_keywords[:80])}\n"
                f"- target_domains: {', '.join(self.config.domain_keywords[:80])}\n"
                f"- output_formats: {', '.join(self.config.output_format_keywords[:80])}\n"
            )
        # Keep JSON braces in prompt templates literal. The config only needs
        # two substitutions, so avoid str.format() parsing schema braces.
        return (
            template
            .replace("{schema_hints}", schema_hints)
            .replace("{text}", text)
        )

    def _extract_structured_api(self, text: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        debug_payload = self._build_api_debug_stub(reason="disabled")
        extraction = self._empty_extraction()

        if not self.config.remote_llm.enabled:
            debug_payload["model_error"] = "remote_llm disabled in config"
            return extraction, debug_payload

        prompt = self._build_llm_prompt(text)
        debug_payload["mode"] = "remote_llm"
        debug_payload["used"] = True
        try:
            raw_response = call_openai_compatible_json(self.config.remote_llm, prompt)
        except Exception as exc:
            debug_payload["model_error"] = str(exc)
            return extraction, debug_payload

        if not isinstance(raw_response, dict):
            debug_payload["model_error"] = "remote_llm returned non-object JSON"
            debug_payload["raw_response"] = raw_response
            return extraction, debug_payload

        debug_payload["raw_response"] = raw_response
        evidence_section = raw_response.get("evidence", {})

        for field in ENUM_FIELDS:
            normalized_values = self._normalize_llm_enum_values(raw_response.get(field, []), field)
            extraction[field] = normalized_values
            extraction["evidence"][field] = self._extract_llm_evidence_items(
                text=text,
                field=field,
                items=evidence_section.get(field, []),
            )
            if not extraction["evidence"][field]:
                extraction["evidence"][field] = [
                    self._build_evidence_entry(
                        field=field,
                        value=value,
                        rule_source="remote_llm",
                        pattern_source="remote_llm_json",
                        matched_text=value,
                        context=self._short_text(text, 180),
                    )
                    for value in normalized_values
                ]
            debug_payload["normalized_hits"][field] = list(normalized_values)
            debug_payload["fallback"][field] = {
                "reason": "remote_llm",
                "used": False,
                "result_count": len(normalized_values),
            }

        metrics = self._normalize_llm_metric_values(raw_response.get("metrics", []))
        extraction["metrics"] = metrics
        extraction["evidence"]["metrics"] = self._extract_llm_evidence_items(
            text=text,
            field="metrics",
            items=evidence_section.get("metrics", []),
            metrics_mode=True,
        )
        if not extraction["evidence"]["metrics"]:
            extraction["evidence"]["metrics"] = [
                self._build_evidence_entry(
                    field="metrics",
                    value=item,
                    rule_source="remote_llm",
                    pattern_source="remote_llm_json",
                    matched_text=f"{item['value']} {item['unit']}".strip(),
                    context=self._short_text(text, 180),
                )
                for item in metrics
            ]
        debug_payload["normalized_hits"]["metrics"] = list(metrics)
        debug_payload["fallback"]["metrics"] = {
            "reason": "remote_llm",
            "used": False,
            "result_count": len(metrics),
        }
        return extraction, debug_payload

    # ────────────────────────────────────────────────────────────────
    # (F) 规则匹配 —— Baseline & Enhanced 核心抽取逻辑
    # ────────────────────────────────────────────────────────────────

    def _extract_structured_baseline(self, text: str, use_action_aliases: bool) -> Dict[str, Any]:
        extraction = self._empty_extraction()
        evidence = extraction["evidence"]

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
            action_values, alias_evidence = self._expand_action_aliases_with_evidence(
                text,
                action_values,
                rule_source="alias_pattern",
                normalize_to_vocab=False,
            )
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

    def _extract_structured_enhanced(
        self,
        bundle: Dict[str, Any],
        gliner_predictions: List[Dict[str, Any]] | None,
        collect_debug: bool,
    ) -> Tuple[Dict[str, Any], Dict[str, Any] | None]:
        extraction = self._empty_extraction()
        evidence = extraction["evidence"]
        debug_payload = self._build_gliner_debug_stub(bundle)

        full_text = bundle.get("full_text", "") or ""
        gliner_text = bundle.get("gliner_text", "") or full_text
        fallback_text = bundle.get("fallback_text", "") or full_text
        gliner_mode = "disabled"
        gliner_available = False

        if bundle.get("gliner_eligible"):
            gliner_available = self._ensure_gliner_model()
            gliner_mode = "gliner" if gliner_available else "gliner_unavailable"
        elif self.config.gliner.enabled and self.config.gliner.english_only_bias and not bundle.get("english_dominant"):
            gliner_mode = "non_english_rule_bias"

        if gliner_mode == "gliner" and gliner_predictions is None:
            gliner_mode = "gliner_inference_failed"
            projected = self._empty_gliner_projection()
            debug_payload["used"] = False
        elif gliner_predictions is not None and gliner_mode == "gliner":
            projected = self._project_gliner_predictions(gliner_text, gliner_predictions)
            debug_payload["used"] = True
        else:
            projected = self._empty_gliner_projection()
            debug_payload["used"] = False

        debug_payload["available"] = gliner_available
        debug_payload["mode"] = gliner_mode
        debug_payload["model_error"] = self._gliner_load_error
        debug_payload["raw_hits"] = projected["all_raw_hits"]

        for field in ENUM_FIELDS:
            state = projected["fields"][field]
            field_values: List[str] = []
            field_evidence: List[Dict[str, Any]] = []
            fallback_reason = "not_needed"

            if gliner_mode == "gliner":
                field_evidence.extend(state["unknown_evidence"])
                if state["values"]:
                    field_values.extend(state["values"])
                    field_evidence.extend(state["evidence"])
                    supplement_values, supplement_evidence = self._extract_field_fallback(field, fallback_text)
                    field_values, field_evidence = self._merge_field_values_and_evidence(
                        field_values,
                        field_evidence,
                        supplement_values,
                        supplement_evidence,
                    )
                else:
                    fallback_reason = state["fallback_reason"]
                    fallback_values, fallback_evidence = self._extract_field_fallback(field, fallback_text)
                    field_values.extend(fallback_values)
                    field_evidence.extend(fallback_evidence)
            else:
                fallback_reason = gliner_mode
                fallback_values, fallback_evidence = self._extract_field_fallback(field, fallback_text)
                field_values.extend(fallback_values)
                field_evidence.extend(fallback_evidence)

            extraction[field] = self._dedupe_preserve_order(field_values)
            evidence[field] = field_evidence
            debug_payload["normalized_hits"][field] = state["accepted_hits"]
            debug_payload["fallback"][field] = {
                "reason": fallback_reason,
                "used": fallback_reason != "not_needed",
                "result_count": len(extraction[field]),
            }

        metric_candidates = projected["fields"]["metrics"]["threshold_hits"] if gliner_mode == "gliner" else []
        metrics, metric_evidence, metric_debug = self._extract_metrics_for_enhanced(
            text=full_text,
            candidate_hits=metric_candidates,
            gliner_mode=gliner_mode,
        )
        extraction["metrics"] = metrics
        evidence["metrics"] = metric_evidence
        debug_payload["normalized_hits"]["metrics"] = metric_debug["parsed_metrics"]
        debug_payload["fallback"]["metrics"] = metric_debug["fallback"]

        if not collect_debug:
            return extraction, None
        return extraction, debug_payload

    # ────────────────────────────────────────────────────────────────
    # (G) 关键词与正则匹配（含 Evidence 记录）
    # ────────────────────────────────────────────────────────────────

    def _extract_keywords_with_evidence(
        self,
        text: str,
        patterns: List[Tuple[re.Pattern[str], str]],
        field: str,
        rule_source: str,
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
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

    def _extract_field_fallback(self, field: str, text: str) -> Tuple[List[Any], List[Dict[str, Any]]]:
        if field == "action_types":
            values, evidence = self._extract_keywords_with_normalization(
                text,
                self._action_patterns,
                field=field,
                rule_source="keyword_fallback",
            )
            values, alias_evidence = self._expand_action_aliases_with_evidence(
                text,
                values,
                rule_source="alias_fallback",
                normalize_to_vocab=True,
            )
            evidence.extend(alias_evidence)
            return values, evidence

        patterns = getattr(self, FIELD_PATTERN_ATTRS[field])
        return self._extract_keywords_with_normalization(
            text,
            patterns,
            field=field,
            rule_source="keyword_fallback",
        )

    def _extract_keywords_with_normalization(
        self,
        text: str,
        patterns: List[Tuple[re.Pattern[str], str]],
        field: str,
        rule_source: str,
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        seen = set()
        values: List[str] = []
        evidence: List[Dict[str, Any]] = []
        for pattern, _ in patterns:
            for match in pattern.finditer(text):
                matched_text = match.group(0).strip()
                normalized, normalization_kind = self._normalize_to_vocab(matched_text, field)
                if not normalized:
                    continue
                if normalized not in seen:
                    seen.add(normalized)
                    values.append(normalized)
                extra: Dict[str, Any] = {}
                if normalization_kind and normalization_kind != "exact":
                    extra["normalized_from"] = matched_text
                evidence.append(
                    self._build_evidence_entry(
                        field=field,
                        value=normalized,
                        rule_source=rule_source,
                        pattern_source=pattern.pattern,
                        matched_text=matched_text,
                        context=self._context_snippet(text, match.start(), match.end()),
                        extra=extra or None,
                    )
                )
        return values, evidence

    def _expand_action_aliases_with_evidence(
        self,
        text: str,
        action_types: List[str],
        rule_source: str,
        normalize_to_vocab: bool,
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        seen = set(action_types)
        expanded = list(action_types)
        evidence: List[Dict[str, Any]] = []
        for pattern, canonical_action in ACTION_ALIAS_PATTERNS:
            for match in pattern.finditer(text):
                value = canonical_action
                if normalize_to_vocab:
                    normalized, _ = self._normalize_to_vocab(canonical_action, "action_types")
                    if not normalized:
                        continue
                    value = normalized
                if value not in seen:
                    seen.add(value)
                    expanded.append(value)
                matched_text = match.group(0).strip()
                evidence.append(
                    self._build_evidence_entry(
                        field="action_types",
                        value=value,
                        rule_source=rule_source,
                        pattern_source=pattern.pattern,
                        matched_text=matched_text,
                        context=self._context_snippet(text, match.start(), match.end()),
                    )
                )
        return expanded, evidence

    # ────────────────────────────────────────────────────────────────
    # (H) 词汇规范化匹配（多级匹配策略）
    # ────────────────────────────────────────────────────────────────

    def _normalize_to_vocab(self, raw_span: str, field: str) -> Tuple[str | None, str | None]:
        clean_span = self._normalize_surface(raw_span)
        if not clean_span:
            return None, None

        exact_map = self._field_exact_maps[field]
        if clean_span in exact_map:
            return exact_map[clean_span], "exact"

        folded = self._fold_lookup(clean_span)
        if folded in self._field_folded_maps[field]:
            return self._field_folded_maps[field][folded], "exact"

        alias_map = self._field_alias_maps[field]
        if clean_span in alias_map:
            return alias_map[clean_span], "alias"
        if folded in alias_map:
            return alias_map[folded], "alias"

        if len(folded) >= 5:
            best_match: Tuple[int, str] | None = None
            for candidate_folded, canonical in self._field_folded_allowed_values[field].items():
                distance = self._bounded_edit_distance(folded, candidate_folded, max_distance=2)
                if distance is None:
                    continue
                if best_match is None or distance < best_match[0]:
                    best_match = (distance, canonical)
            if best_match is not None:
                return best_match[1], "fuzzy"

        return None, None

    def _normalize_span_candidates(self, raw_span: str, field: str) -> List[Tuple[str, str]]:
        candidates: List[Tuple[str, str]] = []
        seen: set[Tuple[str, str]] = set()

        def add_candidate(value: str | None, normalization_kind: str | None) -> None:
            if not value or not normalization_kind:
                return
            key = (value, normalization_kind)
            if key in seen:
                return
            seen.add(key)
            candidates.append(key)

        normalized, normalization_kind = self._normalize_to_vocab(raw_span, field)
        add_candidate(normalized, normalization_kind)
        if candidates:
            return candidates

        clean_span = self._normalize_surface(raw_span)
        if not clean_span:
            return candidates

        split_parts = [
            part.strip()
            for part in re.split(r"(?:,|/|&|\band\b|\bor\b|\+|with)", clean_span)
            if part and part.strip()
        ]
        for part in split_parts:
            normalized_part, part_kind = self._normalize_to_vocab(part, field)
            add_candidate(normalized_part, f"split_{part_kind}" if part_kind else None)
        if candidates:
            return candidates

        for value in sorted(self._field_allowed_values[field], key=len, reverse=True):
            pattern = re.compile(rf"(?<![a-z0-9]){re.escape(value)}(?![a-z0-9])", re.IGNORECASE)
            if pattern.search(clean_span):
                add_candidate(value, "substring")
        if candidates:
            return candidates

        for alias_key, canonical in self._field_alias_maps[field].items():
            if len(alias_key) < 4 or alias_key != self._normalize_surface(alias_key):
                continue
            pattern = re.compile(rf"(?<![a-z0-9]){re.escape(alias_key)}(?![a-z0-9])", re.IGNORECASE)
            if pattern.search(clean_span):
                add_candidate(canonical, "substring_alias")

        return candidates

    def _redirect_gliner_span(
        self,
        raw_span: str,
        field: str,
    ) -> List[Tuple[str, str, str]]:
        clean_span = self._normalize_surface(raw_span)
        if not clean_span:
            return []

        redirects: List[Tuple[str, str, str]] = []

        def add_redirect(
            target_field: str,
            normalized: str | None,
            normalization_kind: str | None,
        ) -> None:
            if not normalized or not normalization_kind:
                return
            redirects.append((target_field, normalized, normalization_kind))

        if field == "platforms":
            mobile_domain = GLINER_PLATFORM_BOUNDARY_TO_DOMAIN.get(clean_span)
            if mobile_domain:
                redirects.append(("target_domains", mobile_domain, "schema_boundary"))
                return redirects
            normalized, normalization_kind = self._normalize_to_vocab(raw_span, "languages")
            add_redirect("languages", normalized, normalization_kind)
            return redirects

        if field == "languages":
            normalized, normalization_kind = self._normalize_to_vocab(raw_span, "platforms")
            add_redirect("platforms", normalized, normalization_kind)
            if redirects:
                return redirects
            normalized, normalization_kind = self._normalize_to_vocab(raw_span, "output_formats")
            add_redirect("output_formats", normalized, normalization_kind)
            return redirects

        if field == "output_formats":
            normalized, normalization_kind = self._normalize_to_vocab(raw_span, "languages")
            add_redirect("languages", normalized, normalization_kind)
            return redirects

        return redirects

    def _should_filter_gliner_unknown(self, raw_span: str, field: str) -> bool:
        clean_span = self._normalize_surface(raw_span)
        if not clean_span:
            return True

        if field == "platforms" and clean_span in GLINER_PLATFORM_BOUNDARY_FILTER:
            return True
        if field == "platforms" and clean_span in GLINER_PLATFORM_OUT_OF_SCHEMA:
            return True
        if field == "languages" and clean_span in GLINER_LANGUAGE_OUT_OF_SCHEMA:
            return True
        if field == "action_types" and clean_span in GLINER_GENERIC_ACTION_NOUNS:
            return True
        if field == "output_formats" and clean_span in GLINER_GENERIC_OUTPUT_META:
            return True
        return False

    def _merge_field_values_and_evidence(
        self,
        base_values: List[str],
        base_evidence: List[Dict[str, Any]],
        supplement_values: List[str],
        supplement_evidence: List[Dict[str, Any]],
    ) -> Tuple[List[str], List[Dict[str, Any]]]:
        merged_values = list(base_values)
        merged_evidence = list(base_evidence)
        seen = set(base_values)
        for value in supplement_values:
            if value in seen:
                continue
            seen.add(value)
            merged_values.append(value)
        merged_evidence.extend(supplement_evidence)
        return merged_values, merged_evidence

    # 标准的 Levenshtein 编辑距离，加了一个提前退出优化：如果当前行的最小编辑距离已经超过 max_distance，直接返回 None。这样对于长串的 fuzzy 匹配不会做无用的全表扫描。
    @staticmethod
    def _bounded_edit_distance(left: str, right: str, max_distance: int) -> int | None:
        if abs(len(left) - len(right)) > max_distance:
            return None
        previous = list(range(len(right) + 1))
        for i, char_left in enumerate(left, start=1):
            current = [i]
            min_current = current[0]
            for j, char_right in enumerate(right, start=1):
                insert_cost = current[j - 1] + 1
                delete_cost = previous[j] + 1
                replace_cost = previous[j - 1] + (char_left != char_right)
                score = min(insert_cost, delete_cost, replace_cost)
                current.append(score)
                min_current = min(min_current, score)
            if min_current > max_distance:
                return None
            previous = current
        return previous[-1] if previous[-1] <= max_distance else None

    # ────────────────────────────────────────────────────────────────
    # (I) Metrics 抽取（独立正则流水线）
    # ────────────────────────────────────────────────────────────────

    def _extract_metrics(self, text: str) -> List[Dict[str, str]]:
        metrics, _ = self._extract_metrics_with_evidence(text)
        return metrics

    def _extract_metrics_with_evidence(
        self,
        text: str,
        rule_source: str = "metric_regex",
        pattern_source_prefix: str = "",
        context_override: str | None = None,
    ) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
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
                    "context": context_override or matched_text,
                    "field": "metrics",
                    "rule_source": rule_source,
                    "pattern_source": f"{pattern_source_prefix}{pattern.pattern}",
                    "matched_text": matched_text,
                }
                metrics.append(metric_item)
                evidence.append(dict(metric_item))
        return metrics, evidence

    def _extract_metrics_for_enhanced(
        self,
        text: str,
        candidate_hits: List[Dict[str, Any]],
        gliner_mode: str,
    ) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]], Dict[str, Any]]:
        debug_payload = {
            "parsed_metrics": [],
            "fallback": {"reason": "metric_regex", "used": False, "result_count": 0},
        }

        if gliner_mode != "gliner":
            metrics, evidence = self._extract_metrics_with_evidence(text)
            debug_payload["fallback"] = {
                "reason": gliner_mode,
                "used": True,
                "result_count": len(metrics),
            }
            debug_payload["parsed_metrics"] = metrics
            return metrics, evidence, debug_payload

        if not candidate_hits:
            metrics, evidence = self._extract_metrics_with_evidence(text)
            debug_payload["fallback"] = {
                "reason": "no_hits",
                "used": True,
                "result_count": len(metrics),
            }
            debug_payload["parsed_metrics"] = metrics
            return metrics, evidence, debug_payload

        candidate_evidence = []
        parsed_metrics: List[Dict[str, str]] = []
        parsed_evidence: List[Dict[str, Any]] = []
        seen_metric_keys = set()
        any_parse_success = False

        for candidate in candidate_hits:
            candidate_evidence.append(
                self._build_evidence_entry(
                    field="metrics",
                    value=candidate["text"],
                    rule_source="gliner_direct",
                    pattern_source=candidate["label"],
                    matched_text=candidate["text"],
                    context=candidate["context"],
                    extra={"score": candidate["score"]},
                )
            )
            metrics, evidence = self._extract_metrics_with_evidence(
                candidate["text"],
                rule_source="metric_regex",
                pattern_source_prefix="candidate:",
                context_override=candidate["context"],
            )
            if metrics:
                any_parse_success = True
            for metric_item, metric_evidence in zip(metrics, evidence):
                key = f"{metric_item['value']}-{metric_item['unit']}"
                if key in seen_metric_keys:
                    continue
                seen_metric_keys.add(key)
                parsed_metrics.append(metric_item)
                parsed_evidence.append(metric_evidence)

        debug_payload["parsed_metrics"] = parsed_metrics
        if any_parse_success:
            debug_payload["fallback"] = {
                "reason": "not_needed",
                "used": False,
                "result_count": len(parsed_metrics),
            }
        else:
            debug_payload["fallback"] = {
                "reason": "candidate_parse_failed",
                "used": False,
                "result_count": 0,
            }
        return parsed_metrics, candidate_evidence + parsed_evidence, debug_payload

    # ────────────────────────────────────────────────────────────────
    # (J) GLiNER 模型生命周期（加载/预测/投影）
    # ────────────────────────────────────────────────────────────────

    def _build_gliner_debug_stub(self, bundle: Dict[str, Any], reason: str = "disabled") -> Dict[str, Any]:
        return {
            "enabled": self.config.gliner.enabled,
            "available": False,
            "used": False,
            "mode": reason,
            "model_name": self.config.gliner.model_name,
            "device": self.config.gliner.device,
            "english_dominant": bundle.get("english_dominant") if bundle else None,
            "raw_hits": [],
            "normalized_hits": {field: [] for field in EXTRACTED_FIELDS},
            "fallback": {
                field: {"reason": reason, "used": reason not in {"baseline_variant", "empty_text"}, "result_count": 0}
                for field in EXTRACTED_FIELDS
            },
            "model_error": self._gliner_load_error,
        }

    def _empty_gliner_projection(self) -> Dict[str, Any]:
        fields = {}
        for field in EXTRACTED_FIELDS:
            fields[field] = {
                "raw_hits": [],
                "threshold_hits": [],
                "values": [],
                "evidence": [],
                "unknown_evidence": [],
                "accepted_hits": [],
                "fallback_reason": "no_hits",
            }
        return {"fields": fields, "all_raw_hits": []}

    def _project_gliner_predictions(
        self,
        text: str,
        predictions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        projection = self._empty_gliner_projection()
        all_raw_hits: List[Dict[str, Any]] = []

        def append_projected_value(
            target_field: str,
            normalized: str,
            raw_text: str,
            label: str,
            score: float,
            context: str,
            normalization_kind: str,
            rule_source: str,
            extra: Dict[str, Any] | None = None,
        ) -> None:
            payload = dict(extra or {})
            projection["fields"][target_field]["values"].append(normalized)
            projection["fields"][target_field]["evidence"].append(
                self._build_evidence_entry(
                    field=target_field,
                    value=normalized,
                    rule_source=rule_source,
                    pattern_source=label,
                    matched_text=raw_text,
                    context=context,
                    extra=payload or None,
                )
            )
            projection["fields"][target_field]["accepted_hits"].append(
                {
                    "value": normalized,
                    "label": label,
                    "score": round(score, 4),
                    "matched_text": raw_text,
                    "normalization_kind": normalization_kind,
                }
            )

        for prediction in predictions:
            label = str(prediction.get("label") or prediction.get("entity") or "").strip()
            field = self._label_to_field.get(label.lower())
            if not field:
                continue

            start, end = self._resolve_prediction_offsets(text, prediction)
            raw_text = self._resolve_prediction_text(text, prediction, start, end)
            score = float(prediction.get("score", 0.0) or 0.0)
            context = self._context_snippet(text, start, end)
            debug_entry = {
                "field": field,
                "label": label,
                "text": raw_text,
                "score": round(score, 4),
                "start": start,
                "end": end,
                "context": context,
            }
            projection["fields"][field]["raw_hits"].append(debug_entry)
            all_raw_hits.append(debug_entry)

            threshold = self._gliner_thresholds.get(field, self._gliner_min_threshold)
            if score < threshold:
                continue

            projection["fields"][field]["threshold_hits"].append(debug_entry)

            if field == "metrics":
                projection["fields"][field]["accepted_hits"].append(
                    {
                        "text": raw_text,
                        "label": label,
                        "score": round(score, 4),
                        "context": context,
                    }
                )
                continue

            normalized_candidates = self._normalize_span_candidates(raw_text, field)
            if normalized_candidates:
                for normalized, normalization_kind in normalized_candidates:
                    rule_source = "gliner_direct"
                    extra: Dict[str, Any] = {"score": round(score, 4)}
                    if normalization_kind != "exact" or self._fold_lookup(raw_text) != self._fold_lookup(normalized):
                        rule_source = "gliner_normalized"
                        extra["normalized_from"] = raw_text
                    append_projected_value(
                        target_field=field,
                        normalized=normalized,
                        raw_text=raw_text,
                        label=label,
                        score=score,
                        context=context,
                        normalization_kind=normalization_kind,
                        rule_source=rule_source,
                        extra=extra,
                    )
            else:
                redirected = self._redirect_gliner_span(raw_text, field)
                if redirected:
                    for target_field, normalized, normalization_kind in redirected:
                        append_projected_value(
                            target_field=target_field,
                            normalized=normalized,
                            raw_text=raw_text,
                            label=label,
                            score=score,
                            context=context,
                            normalization_kind=f"redirect_{normalization_kind}",
                            rule_source="gliner_reassigned",
                            extra={
                                "score": round(score, 4),
                                "reassigned_from_field": field,
                                "normalized_from": raw_text,
                            },
                        )
                    continue

                if self._should_filter_gliner_unknown(raw_text, field):
                    continue

                projection["fields"][field]["unknown_evidence"].append(
                    self._build_evidence_entry(
                        field=field,
                        value=raw_text,
                        rule_source="gliner_unknown",
                        pattern_source=label,
                        matched_text=raw_text,
                        context=context,
                        extra={"score": round(score, 4)},
                    )
                )

        for field in EXTRACTED_FIELDS:
            raw_hits = projection["fields"][field]["raw_hits"]
            threshold_hits = projection["fields"][field]["threshold_hits"]
            values = projection["fields"][field]["values"]
            if field != "metrics" and values:
                fallback_reason = "not_needed"
            elif not raw_hits:
                fallback_reason = "no_hits"
            elif not threshold_hits:
                fallback_reason = "below_threshold"
            elif field != "metrics" and not values:
                fallback_reason = "normalization_failed"
            else:
                fallback_reason = "not_needed"
            projection["fields"][field]["values"] = self._dedupe_preserve_order(values)
            projection["fields"][field]["fallback_reason"] = fallback_reason

        projection["all_raw_hits"] = all_raw_hits
        return projection

    def _resolve_prediction_offsets(
        self,
        text: str,
        prediction: Dict[str, Any],
    ) -> Tuple[int, int]:
        start = prediction.get("start")
        end = prediction.get("end")
        if isinstance(start, int) and isinstance(end, int) and 0 <= start <= end <= len(text):
            return start, end
        raw_text = str(prediction.get("text") or prediction.get("span") or "").strip()
        if raw_text:
            match_start = text.lower().find(raw_text.lower())
            if match_start >= 0:
                return match_start, match_start + len(raw_text)
        return 0, min(len(text), len(raw_text))

    def _resolve_prediction_text(
        self,
        text: str,
        prediction: Dict[str, Any],
        start: int,
        end: int,
    ) -> str:
        raw_text = str(prediction.get("text") or prediction.get("span") or "").strip()
        if raw_text:
            return raw_text
        if 0 <= start <= end <= len(text):
            return text[start:end].strip()
        return ""

    def _ensure_gliner_model(self) -> bool:
        if not self.config.gliner.enabled:
            return False
        if self._gliner_checked:
            return self._gliner_model is not None
        self._gliner_checked = True

        try:
            from gliner import GLiNER
        except Exception as exc:  # pragma: no cover - import path depends on runtime env
            self._gliner_load_error = f"gliner import failed: {exc}"
            self._gliner_model = None
            return False

        try:
            kwargs: Dict[str, Any] = {}
            if self.config.gliner.cache_dir is not None:
                kwargs["cache_dir"] = str(self.config.gliner.cache_dir)
            model = GLiNER.from_pretrained(self.config.gliner.model_name, **kwargs)
            device = self.config.gliner.device.strip().lower()
            if device and device != "auto" and hasattr(model, "to"):
                model = model.to(device)
            self._gliner_model = model
            self._gliner_load_error = None
            return True
        except Exception as exc:  # pragma: no cover - model loading depends on runtime env
            self._gliner_load_error = f"gliner load failed: {exc}"
            self._gliner_model = None
            return False

    def _predict_gliner_single(self, text: str) -> List[Dict[str, Any]] | None:
        batch_predictions = self._predict_gliner_batch([text])
        return batch_predictions[0] if batch_predictions else None

    def _predict_gliner_batch(self, texts: Sequence[str]) -> List[List[Dict[str, Any]]] | None:
        if not texts:
            return []
        if not self._ensure_gliner_model():
            return None

        assert self._gliner_model is not None
        model = self._gliner_model
        base_kwargs: Dict[str, Any] = {
            "threshold": self._gliner_min_threshold,
            "multi_label": True,
            "flat_ner": False,
            "batch_size": self.config.gliner.batch_size,
        }

        def run_chunk(chunk_texts: List[str]) -> List[List[Dict[str, Any]]] | None:
            kwargs = dict(base_kwargs)
            try:
                if hasattr(model, "batch_predict_entities"):
                    predictions = model.batch_predict_entities(chunk_texts, self._gliner_labels, **kwargs)
                else:
                    predictions = model.inference(chunk_texts, self._gliner_labels, **kwargs)
            except TypeError:
                kwargs.pop("batch_size", None)
                try:
                    if hasattr(model, "batch_predict_entities"):
                        predictions = model.batch_predict_entities(chunk_texts, self._gliner_labels, **kwargs)
                    else:
                        predictions = model.inference(chunk_texts, self._gliner_labels, **kwargs)
                except Exception as exc:  # pragma: no cover - runtime API mismatch
                    self._gliner_load_error = f"gliner inference failed: {exc}"
                    return None
            except Exception as exc:  # pragma: no cover - runtime model failure
                self._gliner_load_error = f"gliner inference failed: {exc}"
                return None

            normalized_chunk: List[List[Dict[str, Any]]] = []
            for batch_item in predictions or []:
                if isinstance(batch_item, list):
                    normalized_chunk.append([dict(item) for item in batch_item if isinstance(item, dict)])
                else:
                    normalized_chunk.append([])
            while len(normalized_chunk) < len(chunk_texts):
                normalized_chunk.append([])
            return normalized_chunk

        batch_size = max(1, int(self.config.gliner.batch_size))
        normalized_predictions: List[List[Dict[str, Any]]] = []
        for start in range(0, len(texts), batch_size):
            chunk_texts = list(texts[start : start + batch_size])
            chunk_predictions = run_chunk(chunk_texts)
            if chunk_predictions is not None:
                normalized_predictions.extend(chunk_predictions)
                continue

            # If one batch fails, fall back to per-document inference instead of dropping the whole corpus.
            for text in chunk_texts:
                single_predictions = run_chunk([text])
                if single_predictions is not None and single_predictions:
                    normalized_predictions.append(single_predictions[0])
                else:
                    normalized_predictions.append([])

        while len(normalized_predictions) < len(texts):
            normalized_predictions.append([])
        return normalized_predictions

    # ────────────────────────────────────────────────────────────────
    # (K) 批量文档处理（全量抽取流程）
    # ────────────────────────────────────────────────────────────────

    def _prepare_document_input(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        skill_name = doc.get("skill_name", "")
        description = doc.get("description", "")
        external_skill_text = self._read_external_skill_text(doc)
        skill_md_raw_text = doc.get("skill_md_raw_text", "")
        skill_md = doc.get("skill_md", "")
        category = doc.get("category", "")
        extraction_text = external_skill_text or skill_md_raw_text or skill_md or description or ""
        bundle = self._build_text_bundle(skill_name, category, description, extraction_text)
        return {
            "doc": doc,
            "bundle": bundle,
            "description_preview": self._short_text(description, 200) if description else "",
        }

    def get_document_source_text(self, doc: Dict[str, Any]) -> str:
        return str(self._prepare_document_input(doc)["bundle"].get("full_text", ""))

    def _prepare_document_inputs(self) -> List[Dict[str, Any]]:
        if not self.documents:
            self.load_data()

        return [self._prepare_document_input(doc) for doc in self.documents]

    def _extract_documents_variant(
        self,
        prepared_docs: Sequence[Dict[str, Any]],
        variant: str,
    ) -> List[Dict[str, Any]]:
        if variant == "baseline":
            return [
                self._extract_structured_baseline(item["bundle"]["full_text"], use_action_aliases=False)
                for item in prepared_docs
            ]

        if variant == "api":
            return [
                self._extract_structured_api(item["bundle"]["full_text"])[0]
                for item in prepared_docs
            ]

        predictions_by_index: List[List[Dict[str, Any]] | None] = [None] * len(prepared_docs)
        eligible_indices = [
            index for index, item in enumerate(prepared_docs) if item["bundle"].get("gliner_eligible")
        ]
        if eligible_indices:
            texts = [prepared_docs[index]["bundle"]["gliner_text"] for index in eligible_indices]
            batch_predictions = self._predict_gliner_batch(texts)
            if batch_predictions is not None:
                for index, predictions in zip(eligible_indices, batch_predictions):
                    predictions_by_index[index] = predictions

        extractions: List[Dict[str, Any]] = []
        for index, item in enumerate(prepared_docs):
            extraction, _ = self._extract_structured_enhanced(
                bundle=item["bundle"],
                gliner_predictions=predictions_by_index[index],
                collect_debug=False,
            )
            extractions.append(extraction)
        return extractions

    # ────────────────────────────────────────────────────────────────
    # (L) 事件构建与输出（extract_all, generate_report, save_results, search）
    # ────────────────────────────────────────────────────────────────

    def _build_event_from_doc(
        self,
        doc: Dict[str, Any],
        description_preview: str,
        extraction: Dict[str, Any],
        variant: str,
    ) -> Dict[str, Any]:
        return {
            "skill_id": doc.get("skill_id", ""),
            "skill_name": doc.get("skill_name", ""),
            "owner": doc.get("owner", ""),
            "category": doc.get("category", ""),
            "detail_url": doc.get("detail_url", ""),
            "description_preview": description_preview,
            "variant": variant,
            "evidence_count": sum(len(items or []) for items in extraction.get("evidence", {}).values()),
            "extraction": extraction,
            "event_summary": self._build_event_summary(doc.get("skill_name", ""), extraction),
            "info_point_count": sum(1 for field in EXTRACTED_FIELDS if extraction.get(field, [])),
        }

    def build_event_records(self, variant: str = "enhanced") -> List[Dict[str, Any]]:
        prepared_docs = self._prepare_document_inputs()
        extractions = self._extract_documents_variant(prepared_docs, variant=variant)
        return [
            self._build_event_from_doc(
                doc=item["doc"],
                description_preview=item["description_preview"],
                extraction=extraction,
                variant=variant,
            )
            for item, extraction in zip(prepared_docs, extractions)
        ]

    def extract_all(self) -> List[Dict[str, Any]]:
        prepared_docs = self._prepare_document_inputs()
        extractions = self._extract_documents_variant(prepared_docs, variant=self.variant)
        self.extraction_results = [
            self._build_event_from_doc(
                doc=item["doc"],
                description_preview=item["description_preview"],
                extraction=extraction,
                variant=self.variant,
            )
            for item, extraction in zip(prepared_docs, extractions)
        ]
        return self.extraction_results

    @staticmethod
    def _build_event_summary(skill_name: str, extraction: Dict[str, Any]) -> str:
        parts = [f"[{skill_name}]"]

        actions = extraction.get("action_types", [])
        if actions:
            parts.append(f"actions={'/'.join(actions[:3])}")

        domains = extraction.get("target_domains", [])
        if domains:
            parts.append(f"domains={'/'.join(domains[:2])}")

        platforms = extraction.get("platforms", [])
        if platforms:
            parts.append(f"platforms={'/'.join(platforms[:3])}")

        languages = extraction.get("languages", [])
        if languages:
            parts.append(f"tech={'/'.join(languages[:3])}")

        formats = extraction.get("output_formats", [])
        if formats:
            parts.append(f"formats={'/'.join(formats[:2])}")

        metrics = extraction.get("metrics", [])
        if metrics:
            metric_strs = [f"{m['value']}{m['unit']}" for m in metrics[:2]]
            parts.append(f"metrics={', '.join(metric_strs)}")

        return " | ".join(parts)

    @staticmethod
    def _compact_evidence_sample(event: Dict[str, Any], evidence_entry: Dict[str, Any]) -> Dict[str, Any]:
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
        if not self.extraction_results:
            self.extract_all()

        total = len(self.extraction_results)
        field_counts = Counter()
        field_value_counts: Dict[str, Counter] = defaultdict(Counter)
        info_point_distribution = Counter()

        for event in self.extraction_results:
            extraction = event["extraction"]
            info_point_distribution[event["info_point_count"]] += 1
            for field_name in EXTRACTED_FIELDS:
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
                for field in EXTRACTED_FIELDS
            },
            "top_values_per_field": {
                field: counter.most_common(15) for field, counter in field_value_counts.items()
            },
            "info_point_distribution": dict(sorted(info_point_distribution.items())),
            "documents_with_all_fields": sum(1 for e in self.extraction_results if e["info_point_count"] >= 5),
            "documents_with_no_extraction": sum(1 for e in self.extraction_results if e["info_point_count"] == 0),
            "total_evidence_items": sum(e.get("evidence_count", 0) for e in self.extraction_results),
            "explainability": self._summarize_explainability(),
        }
        return report

    def save_results(self) -> Dict[str, str]:
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
        if not self.extraction_results:
            self.extract_all()

        query_lower = query.lower().strip()
        scored: List[Tuple[float, Dict[str, Any]]] = []
        fields_to_search = [field] if field else ENUM_FIELDS

        for event in self.extraction_results:
            extraction = event["extraction"]
            score = 0.0

            for current_field in fields_to_search:
                values = extraction.get(current_field, [])
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


# ═══════════════════════════════════════════════════════════════════════
# 顶层工具函数
# ═══════════════════════════════════════════════════════════════════════

def print_extraction_results(results: List[Dict[str, Any]], limit: int = 10) -> None:
    for i, event in enumerate(results[:limit], 1):
        print(f"\n[{i}] {event['skill_name']}  (category: {event.get('category', '')})")
        extraction = event["extraction"]
        if extraction["platforms"]:
            print(f"    Platforms: {', '.join(extraction['platforms'])}")
        if extraction["languages"]:
            print(f"    Languages: {', '.join(extraction['languages'])}")
        if extraction["action_types"]:
            print(f"    Actions: {', '.join(extraction['action_types'])}")
        if extraction["target_domains"]:
            print(f"    Domains: {', '.join(extraction['target_domains'])}")
        if extraction["output_formats"]:
            print(f"    Formats: {', '.join(extraction['output_formats'])}")
        if extraction["metrics"]:
            metrics_str = ", ".join(f"{m['value']} {m['unit']}" for m in extraction["metrics"])
            print(f"    Metrics: {metrics_str}")

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
            print(f"    Evidence: {' ; '.join(evidence_lines)}")
        print(f"    Event: {event.get('event_summary', '')}")
        if "match_score" in event:
            print(f"    Match Score: {event['match_score']:.2f}")
