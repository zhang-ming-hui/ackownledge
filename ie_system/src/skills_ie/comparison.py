"""IE 变体比较与说明性报告生成工具。"""

from __future__ import annotations

import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .evaluation import evaluate_extraction


def _save_text_atomic(path: Path, text: str) -> None:
    """以原子方式写入文本报告。"""
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


def _summarize_events(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从事件记录中汇总覆盖率与证据分布。"""
    info_point_distribution = Counter()
    field_coverage = Counter()
    field_evidence_docs = Counter()
    field_evidence_items = Counter()
    field_sources = {field: Counter() for field in [
        "platforms",
        "languages",
        "action_types",
        "target_domains",
        "output_formats",
        "metrics",
    ]}
    global_sources = Counter()

    for event in events:
        info_point_distribution[event.get("info_point_count", 0)] += 1
        extraction = event.get("extraction", {})
        evidence_map = extraction.get("evidence", {}) if isinstance(extraction, dict) else {}
        for field in ["platforms", "languages", "action_types", "target_domains", "output_formats", "metrics"]:
            values = extraction.get(field, [])
            if values:
                field_coverage[field] += 1
            evidence_items = evidence_map.get(field, []) if isinstance(evidence_map, dict) else []
            if evidence_items:
                field_evidence_docs[field] += 1
                field_evidence_items[field] += len(evidence_items)
                for item in evidence_items:
                    source = item.get("rule_source") or item.get("pattern_source") or "unknown"
                    field_sources[field][source] += 1
                    global_sources[source] += 1

    total_docs = len(events)
    explainability = {
        "total_documents": total_docs,
        "field_summary": {
            field: {
                "documents_with_evidence": field_evidence_docs[field],
                "coverage_rate": round(field_evidence_docs[field] / max(total_docs, 1), 4),
                "evidence_items": field_evidence_items[field],
                "evidence_per_document": round(
                    field_evidence_items[field] / max(field_evidence_docs[field], 1), 4
                )
                if field_evidence_docs[field]
                else 0.0,
                "top_sources": [
                    {"source": source, "count": count}
                    for source, count in field_sources[field].most_common(5)
                ],
            }
            for field in field_sources
        },
        "global_source_distribution": [
            {"source": source, "count": count}
            for source, count in global_sources.most_common()
        ],
    }

    return {
        "total_documents": total_docs,
        "info_point_distribution": dict(sorted(info_point_distribution.items())),
        "field_coverage": dict(field_coverage),
        "documents_with_all_fields": sum(1 for event in events if event.get("info_point_count", 0) >= 5),
        "documents_with_no_extraction": sum(1 for event in events if event.get("info_point_count", 0) == 0),
        "explainability": explainability,
    }


def compare_extraction_variants(
    ie_system,
    eval_path: Path,
    variants: Iterable[str] = ("baseline", "enhanced"),
) -> Dict[str, Any]:
    """比较多个 IE 抽取变体。"""
    variants = list(variants)
    variant_reports: Dict[str, Dict[str, Any]] = {}
    variant_summaries: Dict[str, Dict[str, Any]] = {}

    for variant in variants:
        events = ie_system.build_event_records(variant=variant)
        report = evaluate_extraction(events, eval_path)
        report["variant"] = variant
        variant_reports[variant] = report
        variant_summaries[variant] = _summarize_events(events)

    baseline = variant_reports.get("baseline")
    enhanced = variant_reports.get("enhanced")
    field_deltas: Dict[str, Dict[str, float]] = {}
    if baseline and enhanced:
        for field, metrics in enhanced["field_metrics"].items():
            base_metrics = baseline["field_metrics"].get(field, {})
            field_deltas[field] = {
                "precision_delta": round(metrics["avg_precision"] - base_metrics.get("avg_precision", 0.0), 4),
                "recall_delta": round(metrics["avg_recall"] - base_metrics.get("avg_recall", 0.0), 4),
                "f1_delta": round(metrics["avg_f1"] - base_metrics.get("avg_f1", 0.0), 4),
            }

    overall_delta = {}
    if baseline and enhanced:
        overall_delta = {
            "precision_delta": round(
                enhanced["overall"]["precision"] - baseline["overall"]["precision"], 4
            ),
            "recall_delta": round(enhanced["overall"]["recall"] - baseline["overall"]["recall"], 4),
            "f1_delta": round(enhanced["overall"]["f1"] - baseline["overall"]["f1"], 4),
        }

    best_field_by_variant = {}
    for variant, report in variant_reports.items():
        field_metrics = report.get("field_metrics", {})
        if field_metrics:
            best_field_by_variant[variant] = max(
                field_metrics,
                key=lambda field: field_metrics[field].get("avg_f1", 0.0),
            )

    findings = [
        "baseline keeps exact keyword matching only, while enhanced adds action alias expansion",
        "enhanced extraction is the preferred report candidate when F1 and coverage both improve",
    ]
    if overall_delta:
        findings.append(
            f"overall F1 delta: {overall_delta['f1_delta']:+.4f} "
            f"(precision {overall_delta['precision_delta']:+.4f}, recall {overall_delta['recall_delta']:+.4f})"
        )

    return {
        "generated_at": None,
        "eval_path": str(eval_path),
        "variants": variants,
        "variant_reports": variant_reports,
        "variant_summaries": variant_summaries,
        "field_deltas": field_deltas,
        "overall_delta": overall_delta,
        "best_field_by_variant": best_field_by_variant,
        "findings": findings,
    }


def render_comparison_markdown(report: Dict[str, Any], title: str = "IE rule comparison report") -> str:
    """将 IE 规则比较结果渲染为 Markdown。"""
    lines: List[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- Generated at: {report.get('generated_at') or 'n/a'}")
    lines.append(f"- Eval file: {Path(report.get('eval_path', '')).name}")
    lines.append(f"- Variants: {', '.join(report.get('variants', []))}")
    lines.append("")
    lines.append("## Overall metrics")
    lines.append("")
    lines.append("| Variant | Precision | Recall | F1 | Docs with >=5 points | Docs with no extraction |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: |")
    for variant in report.get("variants", []):
        variant_report = report["variant_reports"][variant]
        summary = report["variant_summaries"][variant]
        overall = variant_report["overall"]
        lines.append(
            f"| {variant} | {overall['precision']:.4f} | {overall['recall']:.4f} | {overall['f1']:.4f} | "
            f"{summary['documents_with_all_fields']} | {summary['documents_with_no_extraction']} |"
        )
    lines.append("")
    lines.append("## Field deltas")
    lines.append("")
    lines.append("| Field | Precision delta | Recall delta | F1 delta |")
    lines.append("| --- | ---: | ---: | ---: |")
    for field, deltas in report.get("field_deltas", {}).items():
        lines.append(
            f"| {field} | {deltas['precision_delta']:+.4f} | {deltas['recall_delta']:+.4f} | {deltas['f1_delta']:+.4f} |"
        )
    if report.get("variant_summaries"):
        lines.append("")
        lines.append("## Explainability summary")
        lines.append("")
        lines.append("| Variant | Field | Docs with evidence | Coverage | Evidence items | Top source |")
        lines.append("| --- | --- | ---: | ---: | ---: | --- |")
        for variant in report.get("variants", []):
            summary = report["variant_summaries"].get(variant, {})
            explainability = summary.get("explainability", {})
            field_summary = explainability.get("field_summary", {})
            for field in ["platforms", "languages", "action_types", "target_domains", "output_formats", "metrics"]:
                info = field_summary.get(field, {})
                top_sources = info.get("top_sources", [])
                top_source = top_sources[0]["source"] if top_sources else "-"
                lines.append(
                    f"| {variant} | {field} | {info.get('documents_with_evidence', 0)} | "
                    f"{info.get('coverage_rate', 0.0):.4f} | {info.get('evidence_items', 0)} | {top_source} |"
                )
    lines.append("")
    lines.append("## Innovation notes")
    lines.append("")
    lines.append("- Baseline mode keeps only exact keyword matches, which makes the improvement easy to audit.")
    lines.append("- Enhanced mode adds action alias expansion, which improves recall on semantically similar descriptions.")
    lines.append("- Field-level deltas and coverage stats make the comparison suitable for report writing and manual review.")
    lines.append("")
    return "\n".join(lines)


def print_comparison_report(report: Dict[str, Any]) -> None:
    """打印 IE 规则比较摘要。"""
    print(f"Eval file: {Path(report.get('eval_path', '')).name}")
    print(f"Variants: {', '.join(report.get('variants', []))}")
    if report.get("overall_delta"):
        delta = report["overall_delta"]
        print(
            f"Overall delta: precision={delta['precision_delta']:+.4f} "
            f"recall={delta['recall_delta']:+.4f} f1={delta['f1_delta']:+.4f}"
        )

    print("\nVariant metrics:")
    for variant in report.get("variants", []):
        variant_report = report["variant_reports"][variant]
        summary = report["variant_summaries"][variant]
        overall = variant_report["overall"]
        print(
            f"  - {variant}: P={overall['precision']:.2%} R={overall['recall']:.2%} "
            f"F1={overall['f1']:.2%} all_fields={summary['documents_with_all_fields']} "
            f"no_extraction={summary['documents_with_no_extraction']}"
        )

    if report.get("field_deltas"):
        print("\nField deltas:")
        for field, deltas in report["field_deltas"].items():
            print(
                f"  - {field}: dP={deltas['precision_delta']:+.4f} "
                f"dR={deltas['recall_delta']:+.4f} dF1={deltas['f1_delta']:+.4f}"
            )

    if report.get("findings"):
        print("\nFindings:")
        for item in report["findings"]:
            print(f"  - {item}")
