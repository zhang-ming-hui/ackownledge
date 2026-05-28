"""Configuration models and loading helpers for the IE subsystem."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "ie_config.json"

DEFAULT_GLINER_LABEL_MAP: Dict[str, str] = {
    "platform or tool": "platforms",
    "programming language or framework": "languages",
    "action or capability": "action_types",
    "target domain or industry": "target_domains",
    "output format or file type": "output_formats",
    "quantitative metric": "metrics",
}

DEFAULT_GLINER_FIELD_THRESHOLDS: Dict[str, float] = {
    "platforms": 0.4,
    "languages": 0.3,
    "action_types": 0.5,
    "target_domains": 0.5,
    "output_formats": 0.3,
    "metrics": 0.6,
}

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


def _resolve_path(value: str | None) -> Path | None:
    if value in (None, ""):
        return None
    path = Path(value)
    return path if path.is_absolute() else (REPO_ROOT / path)


@dataclass(frozen=True)
class PathsConfig:
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
        payload = payload or {}
        label_map = dict(DEFAULT_GLINER_LABEL_MAP)
        label_map.update(payload.get("label_map", {}))

        field_thresholds = dict(DEFAULT_GLINER_FIELD_THRESHOLDS)
        field_thresholds.update(payload.get("field_thresholds", {}))

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
class IEConfig:
    paths: PathsConfig
    platform_keywords: List[str]
    language_keywords: List[str]
    action_keywords: List[str]
    domain_keywords: List[str]
    output_format_keywords: List[str]
    gliner: GLiNERConfig

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "IEConfig":
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
        )

    def ensure_runtime_dirs(self) -> None:
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)
        self.paths.output_dir.mkdir(parents=True, exist_ok=True)
        self.paths.eval_dir.mkdir(parents=True, exist_ok=True)
        if self.gliner.cache_dir is not None:
            self.gliner.cache_dir.mkdir(parents=True, exist_ok=True)

    def resolve_eval_path(self, name_or_path: str | None = None) -> Path:
        if not name_or_path:
            name_or_path = "ground_truth.json"
        path = Path(name_or_path)
        return path if path.is_absolute() else self.paths.eval_dir / path


def load_config(config_path: Path | None = None) -> IEConfig:
    config_path = config_path or DEFAULT_CONFIG_PATH
    with config_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return IEConfig.from_dict(payload)
