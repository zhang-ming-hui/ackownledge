"""IR 运行快照与在线查询结果审查工具。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List

from .config import IRConfig
from .evaluation import evaluate_queries
from .state import load_json
from .text import normalize_text


def _failure_count(report: Dict[str, Any]) -> int:
    """统计失败桶里的样本总数。"""
    failure_buckets = report.get("failure_buckets", {})
    return sum(len(items) for items in failure_buckets.values())


def _coverage_findings(
    eval_file: str,
    query_count: int,
    metrics_by_type: Dict[str, Any],
    metrics: Dict[str, Any],
) -> List[str]:
    """根据覆盖度和指标结构生成问题提示。"""
    findings: List[str] = []
    type_counts = {
        query_type: int(type_metrics.get("count", 0))
        for query_type, type_metrics in (metrics_by_type or {}).items()
    }

    if query_count < 20:
        findings.append(f"{eval_file} 目前只有 {query_count} 条 query，覆盖仍然偏小。")

    sparse_types = [query_type for query_type, count in sorted(type_counts.items()) if count < 3]
    if sparse_types:
        findings.append(
            f"{eval_file} 的 query_type 覆盖不均衡，以下类型不足 3 条: {', '.join(sparse_types)}。"
        )

    if query_count:
        dominant_type, dominant_count = max(type_counts.items(), key=lambda item: item[1], default=("", 0))
        if dominant_type and dominant_count / query_count >= 0.7:
            findings.append(
                f"{eval_file} 里 {dominant_type} 占比过高 ({dominant_count}/{query_count})，容易高估整体效果。"
            )

    if metrics.get("hit_at_k") == 1.0 and metrics.get("mrr_at_k") == 1.0:
        findings.append(f"{eval_file} 当前是满分，更像 benchmark 被打满，不代表检索已经稳定。")

    return findings


def build_live_benchmark_review(
    config: IRConfig,
    engine,
    eval_names: Iterable[str] | None = None,
    top_k: int | None = None,
) -> Dict[str, Any]:
    """实时运行一组 benchmark，并生成前端可消费摘要。"""
    eval_names = list(eval_names or [config.default_eval_set, "multilingual.json"])
    reports: List[Dict[str, Any]] = []

    for eval_name in eval_names:
        eval_path = config.resolve_eval_path(eval_name)
        if not eval_path.exists():
            continue
        report = evaluate_queries(
            engine,
            eval_path=eval_path,
            top_k=top_k or config.default_top_k,
        )
        reports.append(
            {
                "eval_file": Path(report["eval_path"]).name,
                "query_count": report["query_count"],
                "top_k": report["top_k"],
                "metrics": report["metrics"],
                "metrics_by_type": report.get("metrics_by_type", {}),
                "failure_count": _failure_count(report),
            }
        )

    findings: List[str] = []
    if not reports:
        findings.append("未找到可运行的评测集。")
    elif all(report["metrics"]["hit_at_k"] == 1.0 for report in reports):
        findings.append("当前 benchmark 全命中；这不一定是好事，更可能说明评测集偏小或已被打满。")

    for report in reports:
        findings.extend(
            _coverage_findings(
                report["eval_file"],
                report["query_count"],
                report.get("metrics_by_type", {}),
                report["metrics"],
            )
        )

    return {
        "reports": reports,
        "findings": findings,
    }


def review_query_results(
    query: str,
    results: List[Dict[str, Any]],
    eval_matches: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """对单次查询结果做启发式审查。"""
    findings: List[Dict[str, str]] = []
    status = "ok"

    if not query:
        return {"status": "idle", "findings": findings}

    if not results:
        return {
            "status": "blocker",
            "findings": [
                {
                    "level": "blocker",
                    "message": "当前 query 没有返回结果，检索输出不合理。",
                }
            ],
        }

    top_names = [item.get("skill_name", "") for item in results]
    duplicate_names = sorted({name for name in top_names if top_names.count(name) > 1 and name})
    if duplicate_names:
        status = "warning"
        findings.append(
            {
                "level": "warning",
                "message": f"Top 结果里存在重复 skill_name: {', '.join(duplicate_names)}。",
            }
        )

    if len(results) > 1 and (results[0]["score"] - results[1]["score"]) < 0.03:
        status = "warning"
        findings.append(
            {
                "level": "warning",
                "message": "Top1 和 Top2 分差很小，当前 query 的排序稳定性偏弱。",
            }
        )

    weak_evidence = []
    for item in results[:3]:
        snippet = str(item.get("snippet", "")).strip()
        fallback_snippet = f"{item.get('skill_name', '')} | {item.get('category', '')}".strip(" |")
        if not snippet or snippet == fallback_snippet:
            weak_evidence.append(item.get("skill_name", ""))
    if weak_evidence:
        status = "warning"
        findings.append(
            {
                "level": "warning",
                "message": f"前 3 个结果里有弱证据项: {', '.join(weak_evidence)}。",
            }
        )

    if eval_matches:
        expected = {
            name
            for match in eval_matches
            for name in match.get("expected_skill_names", [])
        }
        hit_rank = next((index for index, name in enumerate(top_names, start=1) if name in expected), 0)
        if not hit_rank:
            status = "blocker"
            findings.append(
                {
                    "level": "blocker",
                    "message": f"当前 query 在评测集里有期望答案，但前 {len(results)} 条完全未命中。",
                }
            )
        elif hit_rank > 1:
            status = "warning"
            findings.append(
                {
                    "level": "warning",
                    "message": f"当前 query 命中了评测答案，但只排在第 {hit_rank} 位。",
                }
            )
        else:
            findings.append(
                {
                    "level": "ok",
                    "message": "当前 query 的 Top1 与评测期望一致。",
                }
            )
    else:
        normalized_query = normalize_text(query)
        normalized_top1 = normalize_text(results[0].get("skill_name", ""))
        if normalized_query and normalized_query in normalized_top1:
            findings.append(
                {
                    "level": "ok",
                    "message": "Top1 skill 名称直接覆盖了 query 关键词。",
                }
            )
        else:
            findings.append(
                {
                    "level": "ok",
                    "message": "当前 query 不在 benchmark 里，需要结合结果摘要做人审。",
                }
            )

    return {"status": status, "findings": findings}


def review_runtime_snapshot(config: IRConfig) -> Dict[str, Any]:
    """读取运行时产物并提炼当前系统状态。"""
    metrics_report = load_json(config.paths.metrics_report_file, default={})
    failure_buckets = load_json(config.paths.failure_buckets_file, default={})
    findings: List[str] = []

    if not metrics_report:
        findings.append("当前没有离线 metrics 快照。")
    else:
        findings.extend(
            _coverage_findings(
                Path(metrics_report.get("eval_path", "runtime")).name,
                int(metrics_report.get("query_count", 0)),
                metrics_report.get("metrics_by_type", {}),
                metrics_report.get("metrics", {}),
            )
        )

    total_failures = sum(
        len(items) for items in failure_buckets.get("failure_buckets", {}).values()
    )
    return {
        "metrics_report": metrics_report,
        "failure_buckets": failure_buckets,
        "total_failures": total_failures,
        "findings": findings,
    }
