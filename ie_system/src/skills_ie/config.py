"""Skills IE 配置模块。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "ie_config.json"


def _resolve_path(value: str) -> Path:
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
class IEConfig:
    paths: PathsConfig
    platform_keywords: List[str]
    language_keywords: List[str]
    action_keywords: List[str]
    domain_keywords: List[str]
    output_format_keywords: List[str]

    @classmethod
    def from_dict(cls, payload: Dict) -> "IEConfig":
        paths_payload = payload["paths"]
        paths = PathsConfig(
            data_file=_resolve_path(paths_payload["data_file"]),
            output_dir=_resolve_path(paths_payload["output_dir"]),
            state_dir=_resolve_path(paths_payload["state_dir"]),
            eval_dir=_resolve_path(paths_payload["eval_dir"]),
            extraction_results_file=_resolve_path(paths_payload["extraction_results_file"]),
            extraction_report_file=_resolve_path(paths_payload["extraction_report_file"]),
            evaluation_report_file=_resolve_path(paths_payload["evaluation_report_file"]),
            comparison_report_file=_resolve_path(paths_payload["comparison_report_file"]),
            comparison_report_markdown_file=_resolve_path(
                paths_payload["comparison_report_markdown_file"]
            ),
            project_state_file=_resolve_path(paths_payload["project_state_file"]),
            manual_judgments_file=_resolve_path(paths_payload["manual_judgments_file"]),
        )
        return cls(
            paths=paths,
            platform_keywords=payload.get("platform_keywords", []),
            language_keywords=payload.get("language_keywords", []),
            action_keywords=payload.get("action_keywords", []),
            domain_keywords=payload.get("domain_keywords", []),
            output_format_keywords=payload.get("output_format_keywords", []),
        )

    def ensure_runtime_dirs(self) -> None:
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)
        self.paths.output_dir.mkdir(parents=True, exist_ok=True)
        self.paths.eval_dir.mkdir(parents=True, exist_ok=True)

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
