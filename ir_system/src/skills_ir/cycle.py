"""IR 子系统的单次自治运行周期。

一个 cycle 会串联：
1. 数据集状态检查
2. 可选采集
3. 索引加载/构建
4. 数据健康分析
5. 离线评测
6. 项目状态与建议落盘
"""

from __future__ import annotations

from typing import Dict

from .config import IRConfig
from .data_health import save_data_health_report
from .engine import SkillsIRSystem
from .evaluation import evaluate_queries
from .ingest import dataset_stats, is_stale, run_ingest
from .state import load_json, save_json_atomic, utc_now_iso


def _load_agent_manifest(config: IRConfig) -> Dict:
    """读取代理配置，作为周期报告的一部分。"""
    return load_json(config.paths.agent_config_file, default={"agents": []})


def _load_skills_registry(config: IRConfig) -> Dict:
    """读取技能注册表，便于把系统状态和技能集合关联起来。"""
    return load_json(config.paths.skills_registry_file, default={"skills": []})


def run_cycle(
    config: IRConfig,
    *,
    top_k: int | None = None,
    eval_set: str | None = None,
    run_ingest_step: bool = False,
    headless: bool = True,
) -> Dict:
    """执行一次完整的 IR 运行周期，并返回报告。"""
    config.ensure_runtime_dirs()
    top_k = top_k or config.default_top_k
    eval_path = config.resolve_eval_path(eval_set)

    before_dataset = dataset_stats(config.paths.data_file)
    dataset_is_stale = is_stale(config.paths.data_file, config.data_stale_after_hours)

    ingest_summary = {
        "attempted": run_ingest_step,
        "executed": False,
        "reason": "skipped",
        "details": None,
    }
    if run_ingest_step:
        ingest_summary["executed"] = True
        ingest_summary["reason"] = "requested"
        ingest_summary["details"] = run_ingest(config, headless=headless)
    elif dataset_is_stale:
        ingest_summary["reason"] = "dataset_stale_recommend_ingest"

    engine = SkillsIRSystem(config)
    engine.load_or_build()
    index_summary = engine.summary()

    data_health_report = save_data_health_report(config)

    eval_report = evaluate_queries(engine, eval_path=eval_path, top_k=top_k)
    save_json_atomic(config.paths.metrics_report_file, eval_report)
    save_json_atomic(
        config.paths.failure_buckets_file,
        {
            "generated_at": utc_now_iso(),
            "eval_path": str(eval_path),
            "top_k": top_k,
            "failure_buckets": eval_report["failure_buckets"],
        },
    )

    recommendations: list[str] = []
    failure_count = sum(len(items) for items in eval_report["failure_buckets"].values())
    if dataset_is_stale and not run_ingest_step:
        recommendations.append("数据集已过期，建议运行 ingest 执行新一轮扩库。")
    if failure_count:
        recommendations.append("评测存在失败样例，优先处理 failure_buckets.json 中的高频失败类型。")
    else:
        recommendations.append("当前评测集全部命中，可优先扩展评测集和长尾 query。")

    cycle_report = {
        "generated_at": utc_now_iso(),
        "dataset": {
            "before": before_dataset,
            "after": dataset_stats(config.paths.data_file),
            "is_stale": dataset_is_stale,
        },
        "ingest": ingest_summary,
        "index": {
            "path": str(config.paths.index_file),
            **index_summary,
        },
        "data_health": {
            "path": str(config.paths.data_health_report_file),
            "record_count": data_health_report["record_count"],
            "repo_url_buckets": data_health_report["repo_url_buckets"],
            "important_field_missing_counts": data_health_report["important_field_missing_counts"],
        },
        "evaluation": {
            "eval_path": str(eval_path),
            "top_k": top_k,
            "metrics": eval_report["metrics"],
            "failure_bucket_counts": {
                key: len(value) for key, value in eval_report["failure_buckets"].items()
            },
        },
        "agents": _load_agent_manifest(config),
        "skills_registry": _load_skills_registry(config),
        "recommendations": recommendations,
    }
    save_json_atomic(config.paths.cycle_report_file, cycle_report)

    project_state = {
        "last_cycle_at": cycle_report["generated_at"],
        "dataset": cycle_report["dataset"]["after"],
        "index": cycle_report["index"],
        "data_health": cycle_report["data_health"],
        "latest_metrics": cycle_report["evaluation"],
        "recommendations": recommendations,
    }
    save_json_atomic(config.paths.project_state_file, project_state)
    return cycle_report
