"""
IE 子系统配置模型与加载工具。

配置分为三大块：
  1. PathsConfig    — 所有文件路径（数据、输出、评估、状态）
  2. GLiNERConfig   — GLiNER NER 模型的参数（模型名、阈值、别名映射等）
  3. IEConfig       — 顶层配置：路径 + 关键词列表 + GLiNER 子配置

配置来源：configs/ie_config.json（相对于仓库根目录）。
所有相对路径都相对于 REPO_ROOT 解析。
dataclass 使用 frozen=True 确保运行时不可变，避免意外修改。

关键词结构：
  5 个枚举字段（platforms, languages, action_types, target_domains, output_formats）
  各自维护一个关键词列表和对应的 GLiNER 别名映射。
  metrics 字段不走关键词匹配，而是用正则表达式从文本中提取数字+单位。

GLiNER 集成说明：
  - 模型：urchade/gliner_multi-v2.1（mdeberta-v3-base 多语言 backbone）
  - 标签映射：将 GLiNER 的 6 个标签映射到 IE 的 6 个字段
  - 阈值：每个字段独立的置信度阈值，低于阈值的不采纳
  - 别名：GLiNER 预测出的实体名 → 规范化术语的映射
  - english_only_bias：为 True 时非英文文本跳过 GLiNER，回退到纯规则
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

# ── 路径基础 ──────────────────────────────────────────────────────────
# scripts 目录下的 config.py 向上两级到仓库根
REPO_ROOT = Path(__file__).resolve().parents[2]
# 默认配置文件路径
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "ie_config.json"

# ── GLiNER 默认配置 ────────────────────────────────────────────────────
# 这些默认值在 ie_config.json 未指定对应字段时生效

# GLiNER 标签 → IE 字段名的映射
# GLiNER 模型用自然语言标签做 NER，这里将其映射到结构化的字段名
DEFAULT_GLINER_LABEL_MAP: Dict[str, str] = {
    "platform or tool": "platforms",
    "programming language or framework": "languages",
    "action or capability": "action_types",
    "target domain or industry": "target_domains",
    "output format or file type": "output_formats",
    "quantitative metric": "metrics",
}

# 每个字段的置信度阈值
# GLiNER 输出 score=[0,1]，低于阈值的预测会被丢弃
# 不同字段设置了不同的容错度：
#   - metrics=0.6 较高：数字很具体，宁漏勿错
#   - languages/output_formats=0.3 较低：这些字段的实体更容易识别
DEFAULT_GLINER_FIELD_THRESHOLDS: Dict[str, float] = {
    "platforms": 0.4,
    "languages": 0.3,
    "action_types": 0.5,
    "target_domains": 0.5,
    "output_formats": 0.3,
    "metrics": 0.6,
}

# GLiNER 实体别名映射
# 由于 GLiNER 可能输出多种变体写法（如 "github.com"、"git hub"），
# 通过别名映射将它们统一到规范化术语（如 "github"）
# 结构：{ 字段名 -> { 别名 -> 规范化术语 } }
DEFAULT_GLINER_ALIASES: Dict[str, Dict[str, str]] = {
    "platforms": {
        "github.com": "github",
        "git hub": "github",
        "gitlab.com": "gitlab",
        "bitbucket.org": "bitbucket",
        "google knowledge graph": "google",
        "jd": "jd.com",
        "jingdong": "jd.com",
        "vip": "vip.com",
        "vipshop": "vip.com",
        "xiao hong shu": "xiaohongshu",
        "little red book": "xiaohongshu",
        "wechat": "wechat",
        "we chat": "wechat",
        "x.com": "twitter",
        "x (twitter)": "twitter",
        "hacker news": "hackernews",
    },
    "languages": {
        "react.js": "react",
        "reactjs": "react",
        "vue.js": "vue",
        "vuejs": "vue",
        "angular.js": "angular",
        "nextjs": "next.js",
        "next js": "next.js",
        "nuxtjs": "nuxt",
        "nodejs": "node.js",
        "node js": "node.js",
        "vanilla html": "html",
        "vanilla css": "css",
        "golang": "go",
        "py torch": "pytorch",
        "scikit learn": "scikit-learn",
        "tailwindcss": "tailwind",
        "postgres": "postgresql",
    },
    "action_types": {
        "analysis": "analyze",
        "analytics": "analyze",
        "analyzer": "analyze",
        "optimization": "optimize",
        "optimizer": "optimize",
        "optimized": "optimize",
        "generation": "generate",
        "generator": "generate",
        "generated": "generate",
        "creation": "create",
        "creator": "create",
        "writer": "create",
        "writing": "create",
        "drafting": "create",
        "visualization": "visualize",
        "visualizer": "visualize",
        "validation": "validate",
        "validator": "validate",
        "detection": "detect",
        "detector": "detect",
        "comparison": "compare",
        "comparator": "compare",
        "automation": "automate",
        "automated": "automate",
        "translator": "translate",
        "translation": "translate",
        "scheduler": "schedule",
        "scheduling": "schedule",
        "monitoring": "monitor",
        "reviewer": "review",
        "reviewing": "review",
        "extraction": "extract",
        "extractor": "extract",
        "parser": "parse",
        "parsing": "parse",
        "evaluator": "evaluate",
        "evaluation": "evaluate",
        "design": "design",
        "designer": "design",
        "designing": "design",
    },
    "target_domains": {
        "ecommerce": "e-commerce",
        "electronic commerce": "e-commerce",
        "artificial intelligence": "ai",
        "machine-learning": "machine learning",
        "deep-learning": "deep learning",
        "natural language processing": "nlp",
        "business intelligence": "business intelligence",
        "domain authority": "seo",
        "search engine": "seo",
        "search engines": "seo",
        "rich result": "seo",
        "rich results": "seo",
        "serp": "seo",
        "educational": "education",
        "social": "social media",
        "social networking": "social media",
        "xiaohongshu": "social media",
        "user interface": "ui",
        "front end": "frontend",
        "back end": "backend",
    },
    "output_formats": {
        "jsonld": "json-ld",
        "json ld": "json-ld",
        "json format": "json",
        "json output": "json",
        "css output": "css",
        "csv export": "csv",
        "pdfs": "pdf",
        "md": "markdown",
        "jpeg": "jpg",
        "htm": "html",
        "portable document format": "pdf",
    },
}


# ── 路径解析 ──────────────────────────────────────────────────────────

def _resolve_path(value: str | None) -> Path | None:
    """
    将字符串路径解析为绝对 Path。
    
    相对路径 = 相对于 REPO_ROOT（仓库根目录）。
    空值返回 None，表示该路径未配置。
    """
    if value in (None, ""):
        return None
    path = Path(value)
    return path if path.is_absolute() else (REPO_ROOT / path)


# ── 配置 Dataclass ──────────────────────────────────────────────────────

@dataclass(frozen=True)
class PathsConfig:
    """
    IE 子系统的文件路径配置。
    
    所有路径由 ie_config.json 的 paths 段定义。
    使用 frozen=True 确保创建后不可变。
    
    字段说明：
      data_file              — skills_data.json 数据集路径
      output_dir             — 抽取结果等输出目录
      state_dir              — 项目状态与报告目录
      eval_dir               — 评估数据集目录（ground_truth.json 等）
      extraction_results_file — 抽取结果 JSON 文件
      extraction_report_file  — 抽取覆盖率报告
      evaluation_report_file  — 自动评估报告
      comparison_report_file  — baseline vs enhanced 对比报告
      comparison_report_markdown_file — Markdown 格式对比报告
      project_state_file     — 项目状态快照
      manual_judgments_file  — 人工评价累积文件
    """
    data_file: Path
    output_dir: Path
    state_dir: Path
    eval_dir: Path
    extraction_results_file: Path
    extraction_report_file: Path
    evaluation_report_file: Path
    comparison_report_file: Path
    comparison_report_markdown_file: Path
    project_state_file: Path
    manual_judgments_file: Path


@dataclass(frozen=True)
class GLiNERConfig:
    """
    GLiNER NER 模型的配置。
    
    GLiNER 是一个零样本命名实体识别模型，处理 enhanced 变体的核心推理。
    使用 frozen=True，所有参数在构造时确定，运行时不可变。
    
    字段说明：
      enabled            — 是否启用 GLiNER（false 则全力回退到规则）
      model_name         — HuggingFace 模型名称（默认 urchade/gliner_multi-v2.1）
      device             — 推理设备（"cpu" / "cuda" / "auto"）
      cache_dir          — 模型缓存目录（首次加载后缓存共 2.2GB）
      batch_size         — 批量推理的 batch 大小
      label_map          — GLiNER 标签 → IE 字段的映射
      field_thresholds   — 每个字段的置信度阈值
      aliases            — GLiNER 实体名 → 规范化术语的别名映射
      english_only_bias  — 为 True 时，非英文文本跳过 GLiNER（回退到规则）
    """
    enabled: bool
    model_name: str
    device: str
    cache_dir: Path | None
    batch_size: int
    label_map: Dict[str, str]
    field_thresholds: Dict[str, float]
    aliases: Dict[str, Dict[str, str]]
    english_only_bias: bool

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "GLiNERConfig":
        """
        从 JSON dict 构造 GLiNERConfig。
        
        采用合并策略：配置文件的值覆盖代码中的默认值。
        - label_map：合并而非替换（可添加自定义标签）
        - field_thresholds：合并（可调整个别字段阈值）
        - aliases：合并（可补充新别名，不覆盖已有映射）
        """
        payload = payload or {}
        
        # 标签映射：从默认值开始，用配置覆盖
        label_map = dict(DEFAULT_GLINER_LABEL_MAP)
        label_map.update(payload.get("label_map", {}))

        # 阈值：同样合并策略
        field_thresholds = dict(DEFAULT_GLINER_FIELD_THRESHOLDS)
        field_thresholds.update(payload.get("field_thresholds", {}))

        # 别名：每个字段独立合并
        aliases = {
            field: dict(DEFAULT_GLINER_ALIASES.get(field, {}))
            for field in DEFAULT_GLINER_ALIASES
        }
        for field, field_aliases in payload.get("aliases", {}).items():
            aliases.setdefault(field, {})
            aliases[field].update(field_aliases)

        return cls(
            enabled=bool(payload.get("enabled", True)),
            model_name=str(payload.get("model_name", "urchade/gliner_multi-v2.1")),
            device=str(payload.get("device", "cpu")),
            cache_dir=_resolve_path(payload.get("cache_dir")),
            batch_size=max(1, int(payload.get("batch_size", 16))),
            label_map=label_map,
            field_thresholds={key: float(value) for key, value in field_thresholds.items()},
            aliases=aliases,
            english_only_bias=bool(payload.get("english_only_bias", True)),
        )


@dataclass(frozen=True)
class RemoteLLMConfig:
    enabled: bool
    provider: str
    api_base: str
    api_key_env: str
    model: str
    temperature: float
    max_output_tokens: int
    timeout_seconds: int
    system_prompt: str
    prompt_template: str
    include_schema_hints: bool
    extra_headers: Dict[str, str]

    @classmethod
    def from_dict(cls, payload: Dict[str, Any] | None) -> "RemoteLLMConfig":
        payload = payload or {}
        default_prompt_template = (
            "Extract structured information from the following skill text.\n\n"
            "Return JSON only with this exact schema:\n"
            "{\n"
            '  "platforms": ["..."],\n'
            '  "languages": ["..."],\n'
            '  "action_types": ["..."],\n'
            '  "target_domains": ["..."],\n'
            '  "output_formats": ["..."],\n'
            '  "metrics": [{"value": "...", "unit": "..."}],\n'
            '  "evidence": {\n'
            '    "platforms": [{"value": "...", "quote": "..."}],\n'
            '    "languages": [{"value": "...", "quote": "..."}],\n'
            '    "action_types": [{"value": "...", "quote": "..."}],\n'
            '    "target_domains": [{"value": "...", "quote": "..."}],\n'
            '    "output_formats": [{"value": "...", "quote": "..."}],\n'
            '    "metrics": [{"value": "...", "unit": "...", "quote": "..."}]\n'
            "  }\n"
            "}\n\n"
            "Rules:\n"
            "- Use empty arrays when a field is absent.\n"
            "- Keep values concise and canonical.\n"
            "- Evidence quotes must be short verbatim spans from the input.\n"
            "- Do not include any commentary outside JSON.\n\n"
            "Skill text:\n{text}"
        )
        default_system_prompt = (
            "You are an information extraction engine. "
            "You must return strict JSON and nothing else."
        )
        headers = payload.get("extra_headers", {})
        if not isinstance(headers, dict):
            headers = {}
        return cls(
            enabled=bool(payload.get("enabled", False)),
            provider=str(payload.get("provider", "openai_compatible")),
            api_base=str(payload.get("api_base", "https://api.deepseek.com")),
            api_key_env=str(payload.get("api_key_env", "DEEPSEEK_API_KEY")),
            model=str(payload.get("model", "deepseek-chat")),
            temperature=float(payload.get("temperature", 0.0)),
            max_output_tokens=max(1, int(payload.get("max_output_tokens", 1200))),
            timeout_seconds=max(1, int(payload.get("timeout_seconds", 60))),
            system_prompt=str(payload.get("system_prompt", default_system_prompt)),
            prompt_template=str(payload.get("prompt_template", default_prompt_template)),
            include_schema_hints=bool(payload.get("include_schema_hints", True)),
            extra_headers={str(key): str(value) for key, value in headers.items()},
        )


@dataclass(frozen=True)
class IEConfig:
    """
    IE 子系统顶层配置。
    
    组合了路径、关键词列表和 GLiNER 子配置。
    这是从 ie_config.json 完整加载后的结果。
    
    字段说明：
      paths                  — PathsConfig 对象
      platform_keywords      — 平台关键词列表（用于规则匹配）
      language_keywords      — 语言/框架关键词
      action_keywords        — 动作类型关键词
      domain_keywords        — 领域关键词
      output_format_keywords — 输出格式关键词
      gliner                 — GLiNERConfig 对象
    
    注意：
      metrics 字段不使用关键词列表，而是用正则表达式匹配 '数字+单位'。
      EXTRACTED_FIELDS = [platforms, languages, action_types, target_domains, output_formats, metrics]
      前 5 个是枚举字段（ENUM_FIELDS），使用关键词 + GLiNER 联合抽取；
      metrics 单独处理。
    """
    paths: PathsConfig
    platform_keywords: List[str]
    language_keywords: List[str]
    action_keywords: List[str]
    domain_keywords: List[str]
    output_format_keywords: List[str]
    gliner: GLiNERConfig
    remote_llm: RemoteLLMConfig

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "IEConfig":
        """
        从 JSON dict 构造 IEConfig。
        
        JSON 结构大致为:
        {
          "paths": { ... },
          "platform_keywords": [...],
          "language_keywords": [...],
          "action_keywords": [...],
          "domain_keywords": [...],
          "output_format_keywords": [...],
          "gliner": { ... }
        }
        """
        paths_payload = payload["paths"]
        paths = PathsConfig(
            data_file=_resolve_path(paths_payload["data_file"]) or Path(),
            output_dir=_resolve_path(paths_payload["output_dir"]) or Path(),
            state_dir=_resolve_path(paths_payload["state_dir"]) or Path(),
            eval_dir=_resolve_path(paths_payload["eval_dir"]) or Path(),
            extraction_results_file=_resolve_path(paths_payload["extraction_results_file"]) or Path(),
            extraction_report_file=_resolve_path(paths_payload["extraction_report_file"]) or Path(),
            evaluation_report_file=_resolve_path(paths_payload["evaluation_report_file"]) or Path(),
            comparison_report_file=_resolve_path(paths_payload["comparison_report_file"]) or Path(),
            comparison_report_markdown_file=_resolve_path(
                paths_payload["comparison_report_markdown_file"]
            )
            or Path(),
            project_state_file=_resolve_path(paths_payload["project_state_file"]) or Path(),
            manual_judgments_file=_resolve_path(paths_payload["manual_judgments_file"]) or Path(),
        )
        return cls(
            paths=paths,
            platform_keywords=payload.get("platform_keywords", []),
            language_keywords=payload.get("language_keywords", []),
            action_keywords=payload.get("action_keywords", []),
            domain_keywords=payload.get("domain_keywords", []),
            output_format_keywords=payload.get("output_format_keywords", []),
            gliner=GLiNERConfig.from_dict(payload.get("gliner")),
            remote_llm=RemoteLLMConfig.from_dict(payload.get("remote_llm")),
        )

    def ensure_runtime_dirs(self) -> None:
        """
        确保所有运行时目录存在。
        
        包括：state_dir（报告）、output_dir（结果）、eval_dir（评测集）。
        如果配置了 GLiNER cache_dir，也一并创建。
        幂等操作，已存在的目录不会报错。
        """
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)
        self.paths.output_dir.mkdir(parents=True, exist_ok=True)
        self.paths.eval_dir.mkdir(parents=True, exist_ok=True)
        if self.gliner.cache_dir is not None:
            self.gliner.cache_dir.mkdir(parents=True, exist_ok=True)

    def resolve_eval_path(self, name_or_path: str | None = None) -> Path:
        """
        将评测集名称解析为绝对路径。
        
        如果 name_or_path 已经是绝对路径，直接返回；
        否则认为它是 eval_dir 下的相对路径。
        默认：ground_truth.json
        """
        if not name_or_path:
            name_or_path = "ground_truth.json"
        path = Path(name_or_path)
        return path if path.is_absolute() else self.paths.eval_dir / path


# ── 配置加载入口 ──────────────────────────────────────────────────────

def load_config(config_path: Path | None = None) -> IEConfig:
    """
    从 JSON 文件加载 IE 配置。
    
    config_path=None 时使用默认路径 configs/ie_config.json。
    返回完整的不可变 IEConfig 对象，供 extractor、evaluator 等组件读取。
    """
    config_path = config_path or DEFAULT_CONFIG_PATH
    with config_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return IEConfig.from_dict(payload)
