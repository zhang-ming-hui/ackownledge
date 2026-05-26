"""
信息抽取评估模块。

支持两种评估：
1. 自动评估：对比抽取结果与人工标注的 ground truth
2. 人工评估：记录和统计用户的手动评价
"""
from __future__ import annotations

import json
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

from .config import IEConfig
from .state import load_json, save_json_atomic, utc_now_iso


def _normalize_values(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {
        str(value).strip().lower()
        for value in values
        if str(value).strip()
    }


def evaluate_extraction(
    extraction_results: List[Dict[str, Any]],
    eval_path: Path,
) -> Dict[str, Any]:
    """
    对抽取结果进行自动评估。

    评测集格式（eval JSON）：
    [
      {
        "skill_name": "xxx",
        "expected": {
          "platforms": ["github"],
          "languages": ["python"],
          "action_types": ["audit"],
          "target_domains": ["seo"],
          "output_formats": ["json"],
        }
      }
    ]
    """
    with eval_path.open("r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    # 建立 skill_name -> ground_truth 映射
    gt_map = {item["skill_name"]: item["expected"] for item in ground_truth}

    # 建立 skill_name -> extraction 映射
    ext_map = {}
    for event in extraction_results:
        ext_map[event["skill_name"]] = event["extraction"]

    field_metrics: Dict[str, Dict[str, float]] = {}
    fields = ["platforms", "languages", "action_types", "target_domains", "output_formats"]
    per_case: List[Dict] = []

    for field in fields:
        total_precision = 0.0
        total_recall = 0.0
        count = 0

        for skill_name, expected in gt_map.items():
            if skill_name not in ext_map:
                continue

            expected_set = _normalize_values(expected.get(field, []))
            extracted_set = _normalize_values(ext_map[skill_name].get(field, []))

            if not expected_set and not extracted_set:
                continue

            count += 1
            tp = len(expected_set & extracted_set)
            precision = tp / len(extracted_set) if extracted_set else 0.0
            recall = tp / len(expected_set) if expected_set else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

            total_precision += precision
            total_recall += recall

            per_case.append({
                "skill_name": skill_name,
                "field": field,
                "expected": sorted(expected_set),
                "extracted": sorted(extracted_set),
                "tp": tp,
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
            })

        avg_p = total_precision / count if count else 0.0
        avg_r = total_recall / count if count else 0.0
        avg_f1 = 2 * avg_p * avg_r / (avg_p + avg_r) if (avg_p + avg_r) else 0.0

        field_metrics[field] = {
            "evaluated_count": count,
            "avg_precision": round(avg_p, 4),
            "avg_recall": round(avg_r, 4),
            "avg_f1": round(avg_f1, 4),
        }

    # 总体指标
    all_precisions = [m["avg_precision"] for m in field_metrics.values() if m["evaluated_count"] > 0]
    all_recalls = [m["avg_recall"] for m in field_metrics.values() if m["evaluated_count"] > 0]

    overall_p = sum(all_precisions) / len(all_precisions) if all_precisions else 0.0
    overall_r = sum(all_recalls) / len(all_recalls) if all_recalls else 0.0
    overall_f1 = 2 * overall_p * overall_r / (overall_p + overall_r) if (overall_p + overall_r) else 0.0

    return {
        "eval_path": str(eval_path),
        "generated_at": utc_now_iso(),
        "ground_truth_count": len(ground_truth),
        "matched_documents": len(set(ext_map.keys()) & set(gt_map.keys())),
        "overall": {
            "precision": round(overall_p, 4),
            "recall": round(overall_r, 4),
            "f1": round(overall_f1, 4),
        },
        "field_metrics": field_metrics,
        "per_case": per_case,
    }


def load_manual_judgments(config: IEConfig) -> Dict[str, Any]:
    """加载人工评价结果。"""
    path = config.paths.manual_judgments_file
    return load_json(path, default={"judgments": [], "summary": {}})


def save_manual_judgment(
    config: IEConfig,
    skill_name: str,
    field: str,
    label: str,
    value: str = "",
) -> Dict[str, Any]:
    """保存一条人工评价。"""
    config.ensure_runtime_dirs()
    data = load_manual_judgments(config)
    judgments = data.get("judgments", [])

    # 去重
    judgments = [
        j for j in judgments
        if not (j["skill_name"] == skill_name and j["field"] == field and j.get("value", "") == value)
    ]
    judgments.append({
        "skill_name": skill_name,
        "field": field,
        "value": value,
        "label": label,  # correct / incorrect / partial
        "timestamp": utc_now_iso(),
    })

    # 统计
    summary = compute_manual_metrics(judgments)
    data = {"judgments": judgments, "summary": summary}

    path = config.paths.manual_judgments_file
    save_json_atomic(path, data)
    return summary


def compute_manual_metrics(judgments: List[Dict]) -> Dict[str, Any]:
    """计算人工评价的统计指标。"""
    if not judgments:
        return {}

    total = len(judgments)
    by_label = Counter(j["label"] for j in judgments)
    by_field = defaultdict(lambda: Counter())

    for j in judgments:
        by_field[j["field"]][j["label"]] += 1

    correct = by_label.get("correct", 0)
    partial = by_label.get("partial", 0)
    accuracy = (correct + 0.5 * partial) / total if total else 0.0

    field_accuracy = {}
    for field, counts in by_field.items():
        f_total = sum(counts.values())
        f_correct = counts.get("correct", 0)
        f_partial = counts.get("partial", 0)
        field_accuracy[field] = {
            "total": f_total,
            "correct": f_correct,
            "partial": f_partial,
            "incorrect": counts.get("incorrect", 0),
            "accuracy": round((f_correct + 0.5 * f_partial) / f_total, 4) if f_total else 0,
        }

    return {
        "total_judgments": total,
        "correct": correct,
        "partial": partial,
        "incorrect": by_label.get("incorrect", 0),
        "overall_accuracy": round(accuracy, 4),
        "by_field": field_accuracy,
    }


def print_evaluation_report(report: Dict) -> None:
    """打印评估报告。"""
    print(f"\n评测集: {report['eval_path']}")
    print(f"标注文档数: {report['ground_truth_count']} | 匹配文档数: {report['matched_documents']}")
    print(f"\n总体指标:")
    overall = report["overall"]
    print(f"  Precision: {overall['precision']:.2%}")
    print(f"  Recall:    {overall['recall']:.2%}")
    print(f"  F1:        {overall['f1']:.2%}")

    print(f"\n各字段指标:")
    for field, metrics in report["field_metrics"].items():
        print(
            f"  {field:20s}  P={metrics['avg_precision']:.2%}  "
            f"R={metrics['avg_recall']:.2%}  F1={metrics['avg_f1']:.2%}  "
            f"(n={metrics['evaluated_count']})"
        )


def compare_extraction_variants(
    baseline_results: List[Dict[str, Any]],
    enhanced_results: List[Dict[str, Any]],
    eval_path: Path,
) -> Dict[str, Any]:
    baseline_report = evaluate_extraction(baseline_results, eval_path)
    enhanced_report = evaluate_extraction(enhanced_results, eval_path)

    field_deltas = {}
    for field in baseline_report["field_metrics"]:
        baseline_metrics = baseline_report["field_metrics"][field]
        enhanced_metrics = enhanced_report["field_metrics"].get(field, {})
        field_deltas[field] = {
            "precision_delta": round(
                enhanced_metrics.get("avg_precision", 0.0) - baseline_metrics.get("avg_precision", 0.0),
                4,
            ),
            "recall_delta": round(
                enhanced_metrics.get("avg_recall", 0.0) - baseline_metrics.get("avg_recall", 0.0),
                4,
            ),
            "f1_delta": round(
                enhanced_metrics.get("avg_f1", 0.0) - baseline_metrics.get("avg_f1", 0.0),
                4,
            ),
        }

    return {
        "generated_at": utc_now_iso(),
        "eval_path": str(eval_path),
        "baseline": baseline_report,
        "enhanced": enhanced_report,
        "overall_delta": {
            "precision_delta": round(
                enhanced_report["overall"]["precision"] - baseline_report["overall"]["precision"], 4
            ),
            "recall_delta": round(
                enhanced_report["overall"]["recall"] - baseline_report["overall"]["recall"], 4
            ),
            "f1_delta": round(
                enhanced_report["overall"]["f1"] - baseline_report["overall"]["f1"], 4
            ),
        },
        "field_deltas": field_deltas,
    }


def print_variant_comparison(report: Dict[str, Any]) -> None:
    baseline = report["baseline"]["overall"]
    enhanced = report["enhanced"]["overall"]
    delta = report["overall_delta"]

    print(f"Variant comparison | eval={report['eval_path']}")
    print(
        "  - baseline: "
        f"P={baseline['precision']:.2%} R={baseline['recall']:.2%} F1={baseline['f1']:.2%}"
    )
    print(
        "  - enhanced: "
        f"P={enhanced['precision']:.2%} R={enhanced['recall']:.2%} F1={enhanced['f1']:.2%}"
    )
    print(
        "  - delta: "
        f"dP={delta['precision_delta']:+.4f} dR={delta['recall_delta']:+.4f} dF1={delta['f1_delta']:+.4f}"
    )

    print("\nField deltas:")
    for field, metrics in report["field_deltas"].items():
        print(
            f"  - {field}: "
            f"dP={metrics['precision_delta']:+.4f} "
            f"dR={metrics['recall_delta']:+.4f} "
            f"dF1={metrics['f1_delta']:+.4f}"
        )

    if report.get("baseline_summary") and report.get("enhanced_summary"):
        print("\nCoverage summary:")
        for name in ["baseline", "enhanced"]:
            summary = report.get(f"{name}_summary", {})
            print(
                f"  - {name}: total={summary.get('total_documents', 0)} "
                f"all_fields={summary.get('documents_with_all_fields', 0)} "
                f"no_extraction={summary.get('documents_with_no_extraction', 0)}"
            )

        print("\nExplainability summary:")
        for name in ["baseline", "enhanced"]:
            summary = report.get(f"{name}_summary", {})
            explainability = summary.get("explainability", {})
            field_summary = explainability.get("field_summary", {})
            action_info = field_summary.get("action_types", {})
            top_sources = action_info.get("top_sources", [])
            top_source = top_sources[0]["source"] if top_sources else "n/a"
            print(
                f"  - {name}: action_types evidence_docs={action_info.get('documents_with_evidence', 0)} "
                f"coverage={action_info.get('coverage_rate', 0.0):.2%} top_source={top_source}"
            )


def render_variant_comparison_markdown(report: Dict[str, Any], title: str = "IE variant comparison report") -> str:
    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- Generated at: {report.get('generated_at', '')}")
    lines.append(f"- Eval file: {Path(report.get('eval_path', '')).name}")
    lines.append("")
    lines.append("## Overall metrics")
    lines.append("")
    lines.append("| Variant | Precision | Recall | F1 |")
    lines.append("| --- | ---: | ---: | ---: |")
    for name in ["baseline", "enhanced"]:
        if name not in report:
            continue
        overall = report[name]["overall"]
        lines.append(
            f"| {name} | {overall['precision']:.4f} | {overall['recall']:.4f} | {overall['f1']:.4f} |"
        )
    if report.get("baseline_summary") and report.get("enhanced_summary"):
        lines.append("")
        lines.append("## Coverage summary")
        lines.append("")
        lines.append("| Variant | Total docs | Docs with >=5 points | Docs with no extraction |")
        lines.append("| --- | ---: | ---: | ---: |")
        for name in ["baseline", "enhanced"]:
            summary_key = f"{name}_summary"
            if summary_key not in report:
                continue
            summary = report[summary_key]
            lines.append(
                f"| {name} | {summary['total_documents']} | {summary['documents_with_all_fields']} | "
                f"{summary['documents_with_no_extraction']} |"
            )
        lines.append("")
        lines.append("## Explainability summary")
        lines.append("")
        lines.append(
            "| Variant | Field | Docs with evidence | Coverage | Evidence items | Top source |"
        )
        lines.append("| --- | --- | ---: | ---: | ---: | --- |")
        for name in ["baseline", "enhanced"]:
            summary = report.get(f"{name}_summary", {})
            explainability = summary.get("explainability", {})
            field_summary = explainability.get("field_summary", {})
            for field in [
                "platforms",
                "languages",
                "action_types",
                "target_domains",
                "output_formats",
                "metrics",
            ]:
                info = field_summary.get(field, {})
                top_sources = info.get("top_sources", [])
                top_source = top_sources[0]["source"] if top_sources else "-"
                lines.append(
                    f"| {name} | {field} | {info.get('documents_with_evidence', 0)} | "
                    f"{info.get('coverage_rate', 0.0):.4f} | {info.get('evidence_items', 0)} | {top_source} |"
                )
    lines.append("")
    lines.append("## Field deltas")
    lines.append("")
    lines.append("| Field | Precision delta | Recall delta | F1 delta |")
    lines.append("| --- | ---: | ---: | ---: |")
    for field, metrics in report.get("field_deltas", {}).items():
        lines.append(
            f"| {field} | {metrics['precision_delta']:+.4f} | "
            f"{metrics['recall_delta']:+.4f} | {metrics['f1_delta']:+.4f} |"
        )
    lines.append("")
    lines.append("## Innovation notes")
    lines.append("")
    lines.append("- Baseline keeps exact keyword matching only.")
    lines.append("- Enhanced adds action alias expansion for better recall on semantically similar text.")
    lines.append("- Field-level delta tables make the improvement easy to explain in the report.")
    lines.append("")
    return "\n".join(lines)


def save_text_atomic(path: Path, text: str) -> None:
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
