'''
多模式检索效果比较工具
用于在多个评测集上同时运行 TF-IDF、BM25、Hybrid 三种检索模式，汇总各项指标，
分析哪种模式在哪个指标上更优，并产出可读的报告。
'''

from __future__ import annotations

import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .evaluation import evaluate_queries


def _save_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f"{path.stem}.",
        suffix=f".tmp{path.suffix}",
        delete=False,
    ) as file:
        file.write(text)
        temp_path = Path(file.name)
    temp_path.replace(path)

'''
从单次评测返回的 report 字典中提取汇总的指标总计值，计算平均指标。

report 中包含 metric_totals（一个包含 hit_count、top1_count、reciprocal_rank_sum、recall_sum、precision_sum 的 Counter）和 query_count。

返回字典：hit_at_k, top1_accuracy, mrr_at_k, recall_at_k, precision_at_k，均为平均值（总和除以查询数）。
'''
def _metrics_from_totals(report: Dict[str, Any]) -> Dict[str, float]:
    totals = report.get("metric_totals", {})
    count = max(int(report.get("query_count", 0)), 1)
    return {
        "hit_at_k": float(totals.get("hit_count", 0)) / count,
        "top1_accuracy": float(totals.get("top1_count", 0)) / count,
        "mrr_at_k": float(totals.get("reciprocal_rank_sum", 0.0)) / count,
        "recall_at_k": float(totals.get("recall_sum", 0.0)) / count,
        "precision_at_k": float(totals.get("precision_sum", 0.0)) / count,
    }


'''
失败桶是一个字典：键为失败原因分类（如 “no_match”, “low_rank” 等），值为失败样本列表（每个样本包含 query, expected, top_results 等）。
该函数遍历每个失败桶，取第一个样本格式化输出字符串，便于报告展示。最多返回 6 行，避免报告过长。
'''
def _top_failure_examples(failure_buckets: Dict[str, List[Dict[str, Any]]]) -> List[str]:
    lines: List[str] = []
    for bucket_name, items in sorted(failure_buckets.items()):
        if not items:
            continue
        example = items[0]
        expected = ", ".join(example.get("expected", [])[:5])
        top_results = ", ".join(example.get("top_results", [])[:5])
        lines.append(
            f"{bucket_name}: query={example.get('query', '')} | expected=[{expected}] | top=[{top_results}]"
        )
    return lines[:6]

'''
对每一个评测文件，分别以 tfidf、bm25、hybrid 模式运行检索评测。


'''
def compare_retrieval_modes(
    engine,
    eval_paths: Iterable[Path],
    top_k: int,
    modes: Iterable[str] = ("tfidf", "bm25", "hybrid"),
) -> Dict[str, Any]:
    eval_paths = [Path(path) for path in eval_paths]
    modes = list(modes)

    per_eval_reports: List[Dict[str, Any]] = []
    aggregate: Dict[str, Any] = {}
    aggregate_by_mode: Dict[str, Dict[str, Any]] = {}

    for mode in modes:
        aggregate_by_mode[mode] = {
            "query_count": 0,
            "metric_totals": Counter(),
            "failure_bucket_counts": Counter(),
            "failure_examples": defaultdict(list),
        }

    for eval_path in eval_paths:
        mode_reports: Dict[str, Dict[str, Any]] = {}
        mode_metrics: Dict[str, Dict[str, float]] = {}
        for mode in modes:
            report = evaluate_queries(engine, eval_path=eval_path, top_k=top_k, mode=mode)
            mode_reports[mode] = report
            mode_metrics[mode] = report["metrics"]

            aggregate_mode = aggregate_by_mode[mode]
            aggregate_mode["query_count"] += int(report.get("query_count", 0))
            aggregate_mode["metric_totals"].update(report.get("metric_totals", {}))
            for bucket_name, items in report.get("failure_buckets", {}).items():
                aggregate_mode["failure_bucket_counts"][bucket_name] += len(items)
                if items and len(aggregate_mode["failure_examples"][bucket_name]) < 4:
                    aggregate_mode["failure_examples"][bucket_name].extend(items[:2])

        winners = {}
        for metric_name in ["hit_at_k", "top1_accuracy", "mrr_at_k", "recall_at_k", "precision_at_k"]:
            winners[metric_name] = max(
                modes,
                key=lambda mode: mode_metrics[mode].get(metric_name, 0.0),
            )

        per_eval_reports.append(
            {
                "eval_path": str(eval_path),
                "eval_name": Path(eval_path).name,
                "query_count": next(iter(mode_reports.values())).get("query_count", 0) if mode_reports else 0,
                "top_k": top_k,
                "by_mode": mode_reports,
                "winner_by_metric": winners,
            }
        )

    for mode, payload in aggregate_by_mode.items():
        totals = payload["metric_totals"]
        count = max(payload["query_count"], 1)
        payload["metrics"] = {
            "hit_at_k": float(totals.get("hit_count", 0)) / count,
            "top1_accuracy": float(totals.get("top1_count", 0)) / count,
            "mrr_at_k": float(totals.get("reciprocal_rank_sum", 0.0)) / count,
            "recall_at_k": float(totals.get("recall_sum", 0.0)) / count,
            "precision_at_k": float(totals.get("precision_sum", 0.0)) / count,
        }
        payload["failure_count"] = sum(payload["failure_bucket_counts"].values())
        payload["failure_examples"] = {
            bucket: list(examples[:3]) for bucket, examples in payload["failure_examples"].items()
        }

    baseline_mode = "tfidf" if "tfidf" in aggregate_by_mode else modes[0]
    hybrid_mode = "hybrid" if "hybrid" in aggregate_by_mode else modes[-1]
    best_mode = max(modes, key=lambda mode: aggregate_by_mode[mode]["metrics"]["mrr_at_k"])

    deltas = {}
    if hybrid_mode in aggregate_by_mode and baseline_mode in aggregate_by_mode:
        hybrid_metrics = aggregate_by_mode[hybrid_mode]["metrics"]
        baseline_metrics = aggregate_by_mode[baseline_mode]["metrics"]
        deltas["hybrid_vs_tfidf"] = {
            metric: round(hybrid_metrics[metric] - baseline_metrics[metric], 4)
            for metric in hybrid_metrics
        }

    mode_win_counts = Counter()
    for report in per_eval_reports:
        for metric_name, mode in report["winner_by_metric"].items():
            mode_win_counts[mode] += 1

    findings = [
        f"overall best mode by MRR@K: {best_mode}",
        "hybrid BM25 weight is query-aware, and results expose tfidf/bm25 scores for explainability",
    ]
    if hybrid_mode in aggregate_by_mode:
        findings.append(
            f"hybrid failure_count={aggregate_by_mode[hybrid_mode]['failure_count']} "
            f"with top buckets: {', '.join(list(aggregate_by_mode[hybrid_mode]['failure_bucket_counts'])[:3])}"
        )

    return {
        "generated_at": None,
        "eval_paths": [str(path) for path in eval_paths],
        "top_k": top_k,
        "modes": modes,
        "per_eval_reports": per_eval_reports,
        "aggregate": {
            "by_mode": aggregate_by_mode,
            "best_mode_by_mrr": best_mode,
            "mode_win_counts": dict(mode_win_counts),
            "deltas": deltas,
        },
        "failure_summary": {
            mode: {
                "failure_count": payload["failure_count"],
                "failure_bucket_counts": dict(payload["failure_bucket_counts"]),
                "failure_examples": payload["failure_examples"],
                "top_examples": _top_failure_examples(payload["failure_examples"]),
            }
            for mode, payload in aggregate_by_mode.items()
        },
        "findings": findings,
    }


def render_comparison_markdown(report: Dict[str, Any], title: str = "IR algorithm comparison") -> str:
    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- Generated at: {report.get('generated_at') or 'n/a'}")
    lines.append(f"- Eval sets: {', '.join(Path(p).name for p in report.get('eval_paths', []))}")
    lines.append(f"- Top K: {report.get('top_k')}")
    lines.append(f"- Modes: {', '.join(report.get('modes', []))}")
    lines.append("")
    lines.append("## Aggregate metrics")
    lines.append("")
    lines.append("| Mode | Hit@K | Top1 | MRR@K | Recall@K | Precision@K | Failure Count |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for mode in report.get("modes", []):
        payload = report["aggregate"]["by_mode"][mode]
        metrics = payload["metrics"]
        lines.append(
            f"| {mode} | {metrics['hit_at_k']:.4f} | {metrics['top1_accuracy']:.4f} | "
            f"{metrics['mrr_at_k']:.4f} | {metrics['recall_at_k']:.4f} | "
            f"{metrics['precision_at_k']:.4f} | {payload['failure_count']} |"
        )
    lines.append("")
    lines.append("## Evaluation-set winners")
    lines.append("")
    lines.append("| Eval set | Best Hit | Best Top1 | Best MRR | Best Recall | Best Precision |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for item in report.get("per_eval_reports", []):
        winners = item.get("winner_by_metric", {})
        lines.append(
            f"| {item.get('eval_name', '')} | {winners.get('hit_at_k', '')} | "
            f"{winners.get('top1_accuracy', '')} | {winners.get('mrr_at_k', '')} | "
            f"{winners.get('recall_at_k', '')} | {winners.get('precision_at_k', '')} |"
        )
    lines.append("")
    lines.append("## Failure samples")
    lines.append("")
    for mode, payload in report.get("failure_summary", {}).items():
        lines.append(f"### {mode}")
        lines.append("")
        lines.append(f"- Failure count: {payload.get('failure_count', 0)}")
        for example in payload.get("top_examples", [])[:3]:
            lines.append(f"- {example}")
        lines.append("")
    lines.append("## Innovation notes")
    lines.append("")
    lines.append("- Query-aware hybrid ranking adjusts the BM25 weight by query shape.")
    lines.append("- Search results expose tfidf/bm25 components, which keeps ranking explainable.")
    lines.append("- Failure buckets make regression analysis reproducible and easy to compare.")
    lines.append("")
    return "\n".join(lines)


def print_comparison_report(report: Dict[str, Any]) -> None:
    print(f"Eval sets: {', '.join(Path(p).name for p in report.get('eval_paths', []))}")
    print(f"Top K: {report.get('top_k')} | modes: {', '.join(report.get('modes', []))}")
    print(f"Best mode by MRR@K: {report['aggregate'].get('best_mode_by_mrr', '')}")
    print("\nAggregate metrics:")
    for mode in report.get("modes", []):
        payload = report["aggregate"]["by_mode"][mode]
        metrics = payload["metrics"]
        print(
            f"  - {mode}: Hit@K={metrics['hit_at_k']:.2%} "
            f"Top1={metrics['top1_accuracy']:.2%} "
            f"MRR@K={metrics['mrr_at_k']:.4f} "
            f"Recall@K={metrics['recall_at_k']:.2%} "
            f"Precision@K={metrics['precision_at_k']:.2%} "
            f"Failures={payload['failure_count']}"
        )
    if report.get("findings"):
        print("\nFindings:")
        for item in report["findings"]:
            print(f"  - {item}")
