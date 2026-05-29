"""
信息抽取评估模块。

提供两种评估方式：
  1. 自动评估（evaluate_extraction）：
     对比机器抽取结果与人工标注的 ground truth，计算 P/R/F1。
     评估 5 个枚举字段（platforms, languages, action_types, target_domains, output_formats），
     metrics 字段因结构特殊（[{value, unit}]）不纳入自动评估。

  2. 人工评估（save_manual_judgment / compute_manual_metrics）：
     允许通过 Web UI 对抽取结果做人工判断（correct/incorrect/partial），
     累积统计各字段的准确率。

评估指标说明：
  - Precision（精确率）= TP / (TP + FP)  — 抽取结果中有多少是正确的
  - Recall（召回率）  = TP / (TP + FN)  — 标注结果中有多少被抽出
  - F1 = 2 * P * R / (P + R)           — 精确率和召回率的调和平均

匹配策略：
  使用集合交运算（set intersection）：
    TP = |expected_set ∩ extracted_set|
    FP = |extracted_set - expected_set|
    FN = |expected_set - extracted_set|
  值匹配不区分大小写（统一 lower()）。
"""

from __future__ import annotations

import json
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

from .config import IEConfig
from .state import load_json, save_json_atomic, utc_now_iso


# ═══════════════════════════════════════════════════════════════════════
# 自动评估
# ═══════════════════════════════════════════════════════════════════════

def _normalize_values(values: Any) -> set[str]:
    """
    将字段值列表规范化为小写字符串集合。
    
    用于评价时的集合比较，忽略大小写差异。
    例如 extracted=["Python", "JavaScript"] → {"python", "javascript"}
    """
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
    对抽取结果进行自动评估 —— 计算 Precision / Recall / F1。
    
    参数：
      extraction_results  — extract_all() 的输出事件列表，每项含 skill_name + extraction
      eval_path           — 评测集 JSON 文件路径
    
    评测集 JSON 格式：
      [
        {
          "skill_name": "xxx",
          "expected": {
            "platforms": ["github"],
            "languages": ["python"],
            "action_types": ["audit"],
            "target_domains": ["seo"],
            "output_formats": ["json"]
          }
        }
      ]
    
    注意：
      - metrics 字段不参与自动评估（结构为 [{value, unit}]，难以做集合交集）
      - 若 expected 和 extracted 均为空，该 skill 对该字段不计入评估
      - 返回的 avg_precision/avg_recall/avg_f1 是各 skill 的宏平均
    """
    # 加载 ground truth
    with eval_path.open("r", encoding="utf-8") as f:
        ground_truth = json.load(f)

    # skill_name → expected 映射（加速查找）
    gt_map = {item["skill_name"]: item["expected"] for item in ground_truth}

    # skill_name → extraction 映射
    ext_map = {}
    for event in extraction_results:
        ext_map[event["skill_name"]] = event["extraction"]

    field_metrics: Dict[str, Dict[str, float]] = {}
    # 自动评估仅评估 5 个枚举字段（metrics 除外）
    fields = ["platforms", "languages", "action_types", "target_domains", "output_formats"]
    per_case: List[Dict] = []  # 逐 skill 逐字段的明细

    for field in fields:
        total_precision = 0.0
        total_recall = 0.0
        count = 0  # 有标注的 skill 数

        for skill_name, expected in gt_map.items():
            if skill_name not in ext_map:
                continue  # 该 skill 未被抽取（不应发生，但防御性检查）

            expected_set = _normalize_values(expected.get(field, []))
            extracted_set = _normalize_values(ext_map[skill_name].get(field, []))

            # 双方都为空 → 跳过（不计入评估以避免分母为 0）
            if not expected_set and not extracted_set:
                continue

            count += 1
            tp = len(expected_set & extracted_set)          # 正确抽取的
            precision = tp / len(extracted_set) if extracted_set else 0.0
            recall = tp / len(expected_set) if expected_set else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

            total_precision += precision
            total_recall += recall

            # 记录逐项明细，方便后续分析具体 skill 的表现
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

        # 宏平均：先算每个 skill 的 P/R/F1，再取平均
        avg_p = total_precision / count if count else 0.0
        avg_r = total_recall / count if count else 0.0
        avg_f1 = 2 * avg_p * avg_r / (avg_p + avg_r) if (avg_p + avg_r) else 0.0

        field_metrics[field] = {
            "evaluated_count": count,
            "avg_precision": round(avg_p, 4),
            "avg_recall": round(avg_r, 4),
            "avg_f1": round(avg_f1, 4),
        }

    # ── 总体指标：各字段再取平均 ──
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


# ═══════════════════════════════════════════════════════════════════════
# 人工评估
# ═══════════════════════════════════════════════════════════════════════

def load_manual_judgments(config: IEConfig) -> Dict[str, Any]:
    """
    加载人工评价结果文件。
    
    文件不存在时返回空数据 {'judgments': [], 'summary': {}}。
    """
    path = config.paths.manual_judgments_file
    return load_json(path, default={"judgments": [], "summary": {}})


def save_manual_judgment(
    config: IEConfig,
    skill_name: str,
    field: str,
    label: str,
    value: str = "",
) -> Dict[str, Any]:
    """
    保存一条人工评价，并返回更新后的汇总统计。
    
    参数：
      skill_name  — 被评价的 skill 名
      field       — 字段名（platforms / languages / ...）
      label       — 判断标签：'correct'（正确）、'incorrect'（错误）、'partial'（部分正确）
      value       — 被评价的具体值
    
    去重逻辑：
      同一 (skill_name, field, value) 的旧判断会被覆盖（删除后新增），
      避免同一个抽取值被重复评价。
    """
    config.ensure_runtime_dirs()
    data = load_manual_judgments(config)
    judgments = data.get("judgments", [])

    # 去重：移除同一 skill+field+value 的旧记录
    judgments = [
        j for j in judgments
        if not (j["skill_name"] == skill_name and j["field"] == field and j.get("value", "") == value)
    ]
    judgments.append({
        "skill_name": skill_name,
        "field": field,
        "value": value,
        "label": label,   # correct / incorrect / partial
        "timestamp": utc_now_iso(),
    })

    # 重计算汇总统计
    summary = compute_manual_metrics(judgments)
    data = {"judgments": judgments, "summary": summary}

    path = config.paths.manual_judgments_file
    save_json_atomic(path, data)
    return summary


def compute_manual_metrics(judgments: List[Dict]) -> Dict[str, Any]:
    """
    计算人工评价的统计指标。
    
    指标说明：
      - overall_accuracy：整体准确率 = (correct + 0.5 * partial) / total
        其中 partial 算半对（部分正确的抽取仍有价值）
      - by_field：每个字段的 correct/partial/incorrect 分布 + accuracy
    
    空 judgments 返回 {}。
    """
    if not judgments:
        return {}

    total = len(judgments)
    by_label = Counter(j["label"] for j in judgments)
    by_field = defaultdict(lambda: Counter())

    for j in judgments:
        by_field[j["field"]][j["label"]] += 1

    correct = by_label.get("correct", 0)
    partial = by_label.get("partial", 0)
    # 准确率 = (全对 + 半对×0.5) / 总数
    accuracy = (correct + 0.5 * partial) / total if total else 0.0

    # 各字段独立统计
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


# ═══════════════════════════════════════════════════════════════════════
# 报告打印
# ═══════════════════════════════════════════════════════════════════════

def print_evaluation_report(report: Dict) -> None:
    """
    将评估报告打印到终端。
    
    输出包括：
      - 评测集路径 + 文档数
      - 总体 Precision / Recall / F1
      - 各字段的 P / R / F1 + 评估 skill 数
    """
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


# ═══════════════════════════════════════════════════════════════════════
# 变体对比（baseline vs enhanced）
# ═══════════════════════════════════════════════════════════════════════

def compare_extraction_variants(
    baseline_results: List[Dict[str, Any]],
    enhanced_results: List[Dict[str, Any]],
    eval_path: Path,
) -> Dict[str, Any]:
    """
    比较 baseline 与 enhanced 两个抽取变体的评估结果。
    
    对两个变体分别调用 evaluate_extraction()，然后计算差值。
    返回的 field_deltas 和 overall_delta 体现 enhanced 相对于 baseline 的改进量。
    
    Δ = enhanced - baseline（正数 = 改进，负数 = 退步）
    """
    baseline_report = evaluate_extraction(baseline_results, eval_path)
    enhanced_report = evaluate_extraction(enhanced_results, eval_path)

    # 逐字段计算差值
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
    """
    打印抽取变体对比摘要到终端。
    
    输出：baseline vs enhanced 的 P/R/F1、逐字段差值、覆盖率和证据统计。
    """
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

    # 如果 report 中包含 coverage/explainability 汇总
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
    """
    将变体比较结果渲染为 Markdown 格式。
    
    用于生成可读的对比报告文件（comparison_report.md）。
    包含：总体指标对比表、字段差值表、覆盖率、可解释性统计、创新说明。
    """
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


# ═══════════════════════════════════════════════════════════════════════
# 原子文本写入
# ═══════════════════════════════════════════════════════════════════════

def save_text_atomic(path: Path, text: str) -> None:
    """
    以原子方式保存文本报告（Markdown 等）。
    
    实现与 save_json_atomic 相同：先写临时文件，再原子替换。
    """
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
