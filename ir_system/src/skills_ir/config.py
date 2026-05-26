from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Set


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "configs" / "ir_config.json"


def _resolve_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (REPO_ROOT / path)


@dataclass(frozen=True)
class PathsConfig:
    data_file: Path
    index_file: Path
    eval_dir: Path
    state_dir: Path
    data_health_report_file: Path
    project_state_file: Path
    metrics_report_file: Path
    failure_buckets_file: Path
    comparison_report_file: Path
    comparison_report_markdown_file: Path
    search_results_file: Path
    review_report_file: Path
    cycle_report_file: Path
    agent_config_file: Path
    skills_registry_file: Path


@dataclass(frozen=True)
class IRConfig:
    paths: PathsConfig
    field_weights: Dict[str, float]
    stopwords: Set[str]
    query_expansions: Dict[str, list[str]]
    english_query_expansions: Dict[str, list[str]]
    phrase_boosts: list[Dict]
    default_top_k: int
    default_eval_set: str
    smoke_eval_set: str
    ingest_target_count: int
    ingest_sleep_seconds: float
    data_stale_after_hours: int

    @classmethod
    def from_dict(cls, payload: Dict) -> "IRConfig":
        paths_payload = payload["paths"]
        paths = PathsConfig(
            data_file=_resolve_path(paths_payload["data_file"]),
            index_file=_resolve_path(paths_payload["index_file"]),
            eval_dir=_resolve_path(paths_payload["eval_dir"]),
            state_dir=_resolve_path(paths_payload["state_dir"]),
            data_health_report_file=_resolve_path(paths_payload["data_health_report_file"]),
            project_state_file=_resolve_path(paths_payload["project_state_file"]),
            metrics_report_file=_resolve_path(paths_payload["metrics_report_file"]),
            failure_buckets_file=_resolve_path(paths_payload["failure_buckets_file"]),
            comparison_report_file=_resolve_path(paths_payload["comparison_report_file"]),
            comparison_report_markdown_file=_resolve_path(
                paths_payload["comparison_report_markdown_file"]
            ),
            search_results_file=_resolve_path(paths_payload["search_results_file"]),
            review_report_file=_resolve_path(paths_payload["review_report_file"]),
            cycle_report_file=_resolve_path(paths_payload["cycle_report_file"]),
            agent_config_file=_resolve_path(paths_payload["agent_config_file"]),
            skills_registry_file=_resolve_path(paths_payload["skills_registry_file"]),
        )
        return cls(
            paths=paths,
            field_weights={k: float(v) for k, v in payload["field_weights"].items()},
            stopwords=set(payload["stopwords"]),
            query_expansions={k: list(v) for k, v in payload["query_expansions"].items()},
            english_query_expansions={
                k: list(v) for k, v in payload["english_query_expansions"].items()
            },
            phrase_boosts=list(payload.get("phrase_boosts", [])),
            default_top_k=int(payload.get("default_top_k", 5)),
            default_eval_set=str(payload.get("default_eval_set", "core_relevance.json")),
            smoke_eval_set=str(payload.get("smoke_eval_set", "smoke.json")),
            ingest_target_count=int(payload.get("ingest_target_count", 500)),
            ingest_sleep_seconds=float(payload.get("ingest_sleep_seconds", 0.8)),
            data_stale_after_hours=int(payload.get("data_stale_after_hours", 24)),
        )

    def resolve_eval_path(self, name_or_path: str | None) -> Path:
        if not name_or_path:
            name_or_path = self.default_eval_set
        path = Path(name_or_path)
        return path if path.is_absolute() else self.paths.eval_dir / path

    def ensure_runtime_dirs(self) -> None:
        self.paths.state_dir.mkdir(parents=True, exist_ok=True)


def load_config(config_path: Path | None = None) -> IRConfig:
    config_path = config_path or DEFAULT_CONFIG_PATH
    with config_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    return IRConfig.from_dict(payload)
