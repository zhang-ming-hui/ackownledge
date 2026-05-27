"""IR 检索效果离线评测工具。"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

from .engine import SkillsIRSystem


def evaluate_queries(
    engine: SkillsIRSystem,
    eval_path: Path,
    top_k: int,
    mode: str = "hybrid",
) -> Dict:
    """在单个评测集上执行检索并汇总指标。"""
    with eval_path.open("r", encoding="utf-8") as file:
        cases = json.load(file)

    hit_count = 0
    top1_count = 0
    reciprocal_rank_sum = 0.0
    recall_sum = 0.0
    precision_sum = 0.0
    per_case: List[Dict] = []
    type_stats: Dict[str, Counter] = defaultdict(Counter)
    failure_buckets: Dict[str, list[Dict]] = defaultdict(list)

    for case in cases:
        query = case["query"]
        query_type = case.get("query_type", "general")
        expected = set(case["expected_skill_names"])
        results = engine.search(query, top_k=top_k, mode=mode)
        ranked_names = [item["skill_name"] for item in results]
        matched_expected = expected.intersection(ranked_names)

        rank = 0
        for index, name in enumerate(ranked_names, start=1):
            if name in expected:
                rank = index
                break

        recall_value = len(matched_expected) / max(1, len(expected))
        precision_value = len(matched_expected) / max(1, min(top_k, len(ranked_names) or top_k))
        top1_hit = bool(ranked_names and ranked_names[0] in expected)

        if rank:
            hit_count += 1
            reciprocal_rank_sum += 1.0 / rank
        if top1_hit:
            top1_count += 1
        recall_sum += recall_value
        precision_sum += precision_value

        failure_type = ""
        if not ranked_names:
            failure_type = "empty_results"
        elif not rank:
            failure_type = "missed_expected"
        elif rank > 1:
            failure_type = "not_top1"
        elif recall_value < 1.0 and len(expected) > 1:
            failure_type = "partial_expected_coverage"

        stats = type_stats[query_type]
        stats["count"] += 1
        if rank:
            stats["hits"] += 1
            stats["reciprocal_rank_sum"] += 1.0 / rank
        if top1_hit:
            stats["top1_hits"] += 1
        stats["recall_sum"] += recall_value
        stats["precision_sum"] += precision_value

        if failure_type:
            failure_buckets[failure_type].append(
                {
                    "query": query,
                    "query_type": query_type,
                    "expected": sorted(expected),
                    "top_results": ranked_names[:top_k],
                    "hit_rank": rank or None,
                    "matched_expected": sorted(matched_expected),
                    "recall_at_k": recall_value,
                }
            )

        per_case.append(
            {
                "query": query,
                "query_type": query_type,
                "expected_skill_names": case["expected_skill_names"],
                "ranked_skill_names": ranked_names,
                "matched_expected_skill_names": sorted(matched_expected),
                "expected_count": len(expected),
                "matched_expected_count": len(matched_expected),
                "hit_rank": rank or None,
                "passed": bool(rank),
                "top1_passed": top1_hit,
                "recall_at_k": recall_value,
                "precision_at_k": precision_value,
                "failure_type": failure_type or None,
            }
        )

    total = len(cases) or 1
    metrics_by_type = {}
    for query_type, stats in type_stats.items():
        count = stats["count"] or 1
        metrics_by_type[query_type] = {
            "count": stats["count"],
            "hit_at_k": stats["hits"] / count,
            "top1_accuracy": stats["top1_hits"] / count,
            "mrr_at_k": stats["reciprocal_rank_sum"] / count,
            "recall_at_k": stats["recall_sum"] / count,
            "precision_at_k": stats["precision_sum"] / count,
        }

    return {
        "eval_path": str(eval_path),
        "query_count": len(cases),
        "top_k": top_k,
        "mode": mode,
        "metric_totals": {
            "hit_count": hit_count,
            "top1_count": top1_count,
            "reciprocal_rank_sum": reciprocal_rank_sum,
            "recall_sum": recall_sum,
            "precision_sum": precision_sum,
        },
        "metrics": {
            "hit_at_k": hit_count / total,
            "top1_accuracy": top1_count / total,
            "mrr_at_k": reciprocal_rank_sum / total,
            "recall_at_k": recall_sum / total,
            "precision_at_k": precision_sum / total,
        },
        "metrics_by_type": metrics_by_type,
        "failure_buckets": failure_buckets,
        "cases": per_case,
    }


def compare_retrieval_modes(
    engine: SkillsIRSystem,
    eval_path: Path,
    top_k: int,
    modes: List[str] | None = None,
) -> Dict:
    """比较多种检索模式在同一评测集上的表现。"""
    modes = modes or ["tfidf", "bm25", "hybrid"]
    reports = [evaluate_queries(engine, eval_path, top_k=top_k, mode=mode) for mode in modes]

    summary = []
    metric_names = ["hit_at_k", "top1_accuracy", "mrr_at_k", "recall_at_k", "precision_at_k"]
    for report in reports:
        metrics = report["metrics"]
        summary.append(
            {
                "mode": report["mode"],
                **{metric_name: metrics[metric_name] for metric_name in metric_names},
                "failure_count": sum(len(items) for items in report["failure_buckets"].values()),
            }
        )

    best_by_metric = {}
    for metric_name in metric_names:
        best = max(summary, key=lambda item: item[metric_name])
        best_by_metric[metric_name] = {"mode": best["mode"], "value": best[metric_name]}

    return {
        "eval_path": str(eval_path),
        "top_k": top_k,
        "reports": reports,
        "summary": summary,
        "best_by_metric": best_by_metric,
    }


def print_evaluation_report(report: Dict) -> None:
    """打印单次评测报告。"""
    metrics = report["metrics"]
    print(f"评测集: {report['eval_path']} | 样本数: {report['query_count']} | top_k: {report['top_k']}")
    print(f"Hit@{report['top_k']}: {metrics['hit_at_k']:.2%}")
    print(f"Top1 Accuracy: {metrics['top1_accuracy']:.2%}")
    print(f"MRR@{report['top_k']}: {metrics['mrr_at_k']:.4f}")
    print(f"Recall@{report['top_k']}: {metrics['recall_at_k']:.2%}")
    print(f"Precision@{report['top_k']}: {metrics['precision_at_k']:.2%}")

    if report["metrics_by_type"]:
        print("\n按 query 类型:")
        for query_type, type_metrics in sorted(report["metrics_by_type"].items()):
            print(
                f"  - {query_type}: count={type_metrics['count']} "
                f"Hit@K={type_metrics['hit_at_k']:.2%} "
                f"Top1={type_metrics['top1_accuracy']:.2%} "
                f"MRR@K={type_metrics['mrr_at_k']:.4f} "
                f"Recall@K={type_metrics['recall_at_k']:.2%}"
            )

    failed = sum(len(items) for items in report["failure_buckets"].values())
    print(f"\n失败样例数: {failed}")
    for bucket_name, items in sorted(report["failure_buckets"].items()):
        print(f"  - {bucket_name}: {len(items)}")
        for example in items[:2]:
            expected = ", ".join(example.get("expected", []))
            top_results = ", ".join(example.get("top_results", [])[:5])
            print(
                f"      * query={example.get('query', '')} | "
                f"expected=[{expected}] | top=[{top_results}]"
            )


def print_mode_comparison(report: Dict) -> None:
    """打印模式比较摘要。"""
    print(f"Mode comparison | eval={report['eval_path']} | top_k={report['top_k']}")
    for item in report["summary"]:
        print(
            f"  - {item['mode']}: "
            f"Hit@K={item['hit_at_k']:.2%} "
            f"Top1={item['top1_accuracy']:.2%} "
            f"MRR@K={item['mrr_at_k']:.4f} "
            f"Recall@K={item['recall_at_k']:.2%} "
            f"Precision@K={item['precision_at_k']:.2%} "
            f"failures={item['failure_count']}"
        )

    print("\nBest by metric:")
    for metric_name, item in report["best_by_metric"].items():
        print(f"  - {metric_name}: {item['mode']} ({item['value']:.4f})")
