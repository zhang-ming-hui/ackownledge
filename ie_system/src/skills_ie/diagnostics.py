from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from .config import IEConfig
from .evaluation import evaluate_extraction
from .extractor import SkillsIESystem
from .state import utc_now_iso


EVAL_FIELDS = ["platforms", "languages", "action_types", "target_domains", "output_formats"]


def _normalize_values(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    normalized: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            token = f"{value.get('value', '')} {value.get('unit', '')}".strip().lower()
        else:
            token = str(value).strip().lower()
        if token:
            normalized.add(token)
    return normalized


def evaluate_extraction_micro(
    extraction_results: List[Dict[str, Any]],
    eval_path: Path,
) -> Dict[str, Any]:
    ground_truth = json.loads(eval_path.read_text(encoding="utf-8"))
    gt_map = {item["skill_name"]: item["expected"] for item in ground_truth}
    ext_map = {event["skill_name"]: event["extraction"] for event in extraction_results}

    overall_tp = 0
    overall_fp = 0
    overall_fn = 0
    per_field: Dict[str, Dict[str, int]] = {
        field: {"tp": 0, "fp": 0, "fn": 0, "support": 0, "matched_documents": 0}
        for field in EVAL_FIELDS
    }

    for skill_name, expected in gt_map.items():
        extraction = ext_map.get(skill_name)
        if extraction is None:
            continue
        for field in EVAL_FIELDS:
            expected_set = _normalize_values(expected.get(field, []))
            extracted_set = _normalize_values(extraction.get(field, []))
            if expected_set:
                per_field[field]["support"] += len(expected_set)
            if expected_set or extracted_set:
                per_field[field]["matched_documents"] += 1
            tp = len(expected_set & extracted_set)
            fp = len(extracted_set - expected_set)
            fn = len(expected_set - extracted_set)
            per_field[field]["tp"] += tp
            per_field[field]["fp"] += fp
            per_field[field]["fn"] += fn
            overall_tp += tp
            overall_fp += fp
            overall_fn += fn

    def _prf(tp: int, fp: int, fn: int) -> Dict[str, float]:
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        return {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }

    per_field_metrics = {}
    for field, counts in per_field.items():
        per_field_metrics[field] = {
            **counts,
            **_prf(counts["tp"], counts["fp"], counts["fn"]),
        }

    return {
        "overall": {
            "tp": overall_tp,
            "fp": overall_fp,
            "fn": overall_fn,
            **_prf(overall_tp, overall_fp, overall_fn),
        },
        "field_metrics": per_field_metrics,
    }


def _load_eval_skill_names(eval_path: Path) -> List[str]:
    ground_truth = json.loads(eval_path.read_text(encoding="utf-8"))
    return [item["skill_name"] for item in ground_truth]


def _build_events_for_variant(
    config: IEConfig,
    documents: List[Dict[str, Any]],
    variant: str,
    disable_gliner: bool = False,
) -> List[Dict[str, Any]]:
    actual_config = config
    if disable_gliner:
        actual_config = replace(config, gliner=replace(config.gliner, enabled=False))
    ie = SkillsIESystem(actual_config, variant=variant)
    ie.documents = list(documents)
    return ie.build_event_records(variant=variant)


def _field_support(eval_path: Path) -> Dict[str, int]:
    ground_truth = json.loads(eval_path.read_text(encoding="utf-8"))
    counts = Counter()
    for item in ground_truth:
        expected = item.get("expected", {})
        for field in EVAL_FIELDS:
            if expected.get(field):
                counts[field] += 1
    return {field: counts.get(field, 0) for field in EVAL_FIELDS}


def _case_f1(expected_set: set[str], predicted_set: set[str]) -> float:
    tp = len(expected_set & predicted_set)
    precision = tp / len(predicted_set) if predicted_set else 0.0
    recall = tp / len(expected_set) if expected_set else 0.0
    return round(2 * precision * recall / (precision + recall), 4) if (precision + recall) else 0.0


def summarize_variant_changes(
    regex_events: List[Dict[str, Any]],
    gliner_events: List[Dict[str, Any]],
    eval_path: Path,
) -> Dict[str, Any]:
    ground_truth = json.loads(eval_path.read_text(encoding="utf-8"))
    gt_map = {item["skill_name"]: item["expected"] for item in ground_truth}
    regex_map = {event["skill_name"]: event["extraction"] for event in regex_events}
    gliner_map = {event["skill_name"]: event["extraction"] for event in gliner_events}

    changed_skill_count = 0
    changed_field_count = 0
    gain_field_cases = 0
    hurt_field_cases = 0
    same_field_cases = 0
    samples: List[Dict[str, Any]] = []

    for skill_name, expected in gt_map.items():
        regex_extraction = regex_map.get(skill_name)
        gliner_extraction = gliner_map.get(skill_name)
        if regex_extraction is None or gliner_extraction is None:
            continue
        skill_changed = False
        for field in EVAL_FIELDS:
            expected_set = _normalize_values(expected.get(field, []))
            regex_set = _normalize_values(regex_extraction.get(field, []))
            gliner_set = _normalize_values(gliner_extraction.get(field, []))
            regex_f1 = _case_f1(expected_set, regex_set)
            gliner_f1 = _case_f1(expected_set, gliner_set)
            if regex_f1 < gliner_f1:
                gain_field_cases += 1
            elif regex_f1 > gliner_f1:
                hurt_field_cases += 1
            else:
                same_field_cases += 1
            if regex_set != gliner_set:
                skill_changed = True
                changed_field_count += 1
                if len(samples) < 20:
                    samples.append(
                        {
                            "skill_name": skill_name,
                            "field": field,
                            "expected": sorted(expected_set),
                            "regex": sorted(regex_set),
                            "gliner": sorted(gliner_set),
                            "regex_f1": regex_f1,
                            "gliner_f1": gliner_f1,
                        }
                    )
        if skill_changed:
            changed_skill_count += 1

    return {
        "changed_skill_count": changed_skill_count,
        "changed_field_count": changed_field_count,
        "gain_field_cases": gain_field_cases,
        "hurt_field_cases": hurt_field_cases,
        "same_field_cases": same_field_cases,
        "samples": samples,
    }


def summarize_full_variant_differences(
    regex_events: List[Dict[str, Any]],
    gliner_events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    regex_map = {event["skill_name"]: event["extraction"] for event in regex_events}
    gliner_map = {event["skill_name"]: event["extraction"] for event in gliner_events}

    changed_skill_count = 0
    field_counts = {field: 0 for field in EVAL_FIELDS + ["metrics"]}
    samples: List[Dict[str, Any]] = []

    for skill_name, regex_extraction in regex_map.items():
        gliner_extraction = gliner_map.get(skill_name)
        if gliner_extraction is None:
            continue
        diffs = []
        for field in field_counts:
            regex_set = _normalize_values(regex_extraction.get(field, []))
            gliner_set = _normalize_values(gliner_extraction.get(field, []))
            if regex_set != gliner_set:
                field_counts[field] += 1
                diffs.append(
                    {
                        "field": field,
                        "regex": sorted(regex_set),
                        "gliner": sorted(gliner_set),
                    }
                )
        if diffs:
            changed_skill_count += 1
            if len(samples) < 20:
                samples.append({"skill_name": skill_name, "diffs": diffs})

    return {
        "changed_skill_count": changed_skill_count,
        "field_counts": field_counts,
        "samples": samples,
    }


def _unknown_reason(field: str, value: str) -> str:
    normalized = " ".join(value.lower().split())

    platform_os = {"ios", "android", "macos", "linux", "windows"}
    platform_confusion = {"go", "kotlin", "postgresql", "antd", "gsap", "git", "gh"}
    platform_vocab_gap = {
        "claude code", "mcp", "gemini", "claude", "codex", "chrome", "binance", "solana",
        "sentry", "prisma", "opencode", "foodora", "base", "himalaya", "ccc", "tzst", "dmux"
    }

    language_confusion = {
        "github", "figma", "android", "supabase", "wordpress", "exa", "stitch", "binance"
    }
    language_schema_gap = {"markdown", "latex"}
    language_tooling = {"claude code", "gemini", "codex", "claude", "opencode", "mcp", "llm"}
    language_vocab_gap = {".net", "ktor", "terraform", "flutter", "bigquery", "npm", "git"}

    output_language = {"typescript", "javascript", "python", "node.js"}
    output_vocab_gap = {"bibtex", "txt", "webm", "word", "marp", "plain text", "og images", "images", "music"}
    output_meta = {
        "output format", "coverage", "field-level", "minimal", "quick chat display",
        "visual-style.md", "design.md", "stdin", "br", "string", "dom manipulation",
        "conventional commits", "http", "urls", "text"
    }

    action_http = {"put", "delete"}
    action_noun = {
        "authentication", "mutations", "pre-built actions", "actions", "error handling", "interactions",
        "cookie management", "crawlability", "accessibility", "navigation", "queries", "form filling",
        "state management", "server actions", "voice cloning", "data loading", "reactivity",
        "rate limiting", "autonomy", "payments", "advanced patterns", "resource management",
        "concurrency", "skill loading", "actionability", "pretooluse"
    }

    target_vocab_gap = {
        "industry", "saas", "tech", "consulting", "enterprise", "business software",
        "b2b", "b2c", "health & fitness"
    }

    if field == "platforms":
        if normalized in platform_os:
            return "schema_scope_os_runtime"
        if normalized == "x":
            return "alias_gap"
        if normalized in platform_confusion:
            return "cross_field_confusion"
        if normalized in platform_vocab_gap:
            return "vocab_missing_platform"
        return "other_platform_unknown"

    if field == "languages":
        if normalized in language_confusion:
            return "cross_field_confusion"
        if normalized in language_schema_gap:
            return "schema_scope_markup_or_doc"
        if normalized in language_tooling:
            return "tool_or_model_name"
        if normalized in language_vocab_gap:
            return "vocab_missing_language_or_framework"
        return "other_language_unknown"

    if field == "output_formats":
        if normalized in output_language:
            return "cross_field_confusion"
        if normalized in output_vocab_gap:
            return "vocab_missing_output_format"
        if normalized in output_meta:
            return "generic_or_meta_span"
        return "other_output_unknown"

    if field == "action_types":
        if normalized in action_http:
            return "protocol_token"
        if normalized in action_noun:
            return "action_noun_needs_alias_or_filter"
        return "other_action_unknown"

    if field == "target_domains":
        if normalized in target_vocab_gap:
            return "vocab_missing_target_domain"
        return "other_target_domain_unknown"

    return "unknown"


def analyze_gliner_unknowns(events: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    total_unknown = 0
    field_reason_counts: Dict[str, Counter] = defaultdict(Counter)
    global_reason_counts: Counter = Counter()
    field_value_counts: Dict[str, Counter] = defaultdict(Counter)
    reason_examples: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    field_unknown_counts: Counter = Counter()
    recommendation_candidates: Counter = Counter()

    for event in events:
        evidence_map = (event.get("extraction") or {}).get("evidence") or {}
        for field, items in evidence_map.items():
            for item in items or []:
                if item.get("rule_source") != "gliner_unknown":
                    continue
                value = str(item.get("value") or "").strip()
                if not value:
                    continue
                reason = _unknown_reason(field, value)
                total_unknown += 1
                field_unknown_counts[field] += 1
                field_reason_counts[field][reason] += 1
                global_reason_counts[reason] += 1
                field_value_counts[field][value] += 1

                if len(reason_examples[reason]) < 8:
                    reason_examples[reason].append(
                        {
                            "skill_name": event.get("skill_name", ""),
                            "field": field,
                            "value": value,
                            "context": item.get("context", ""),
                        }
                    )

                if reason in {
                    "alias_gap",
                    "vocab_missing_platform",
                    "vocab_missing_language_or_framework",
                    "vocab_missing_output_format",
                    "vocab_missing_target_domain",
                }:
                    recommendation_candidates[(field, value, reason)] += 1

    recommendations = []
    for (field, value, reason), count in recommendation_candidates.most_common(25):
        if reason == "alias_gap":
            action = "add alias normalization"
        elif reason.startswith("vocab_missing_"):
            action = "consider extending controlled vocabulary"
        else:
            action = "review normalization rules"
        recommendations.append(
            {
                "field": field,
                "value": value,
                "reason": reason,
                "count": count,
                "suggested_action": action,
            }
        )

    return {
        "total_unknown": total_unknown,
        "field_unknown_counts": dict(field_unknown_counts),
        "global_reason_distribution": [
            {"reason": reason, "count": count} for reason, count in global_reason_counts.most_common()
        ],
        "field_reason_distribution": {
            field: [{"reason": reason, "count": count} for reason, count in counter.most_common()]
            for field, counter in field_reason_counts.items()
        },
        "top_unknown_values_by_field": {
            field: [{"value": value, "count": count} for value, count in counter.most_common(20)]
            for field, counter in field_value_counts.items()
        },
        "reason_examples": dict(reason_examples),
        "recommendations": recommendations,
    }


def build_eval_diagnostic_report(
    config: IEConfig,
    primary_eval_path: Path,
    secondary_eval_path: Path | None = None,
    include_full_compare: bool = True,
    use_cached_full_gliner: bool = True,
) -> Dict[str, Any]:
    documents = json.loads(config.paths.data_file.read_text(encoding="utf-8"))

    datasets = [primary_eval_path]
    if secondary_eval_path and secondary_eval_path != primary_eval_path:
        datasets.append(secondary_eval_path)

    union_names: set[str] = set()
    for eval_path in datasets:
        union_names.update(_load_eval_skill_names(eval_path))
    subset_documents = [doc for doc in documents if doc.get("skill_name") in union_names]

    baseline_events = _build_events_for_variant(config, subset_documents, variant="baseline")
    regex_events = _build_events_for_variant(
        config,
        subset_documents,
        variant="enhanced",
        disable_gliner=True,
    )
    gliner_events = _build_events_for_variant(config, subset_documents, variant="enhanced")

    report: Dict[str, Any] = {
        "generated_at": utc_now_iso(),
        "primary_eval_path": str(primary_eval_path),
        "secondary_eval_path": str(secondary_eval_path) if secondary_eval_path else None,
        "datasets": {},
    }

    variants = {
        "baseline": baseline_events,
        "enhanced_regex": regex_events,
        "enhanced_gliner": gliner_events,
    }

    for eval_path in datasets:
        dataset_key = eval_path.name
        dataset_entry: Dict[str, Any] = {
            "eval_path": str(eval_path),
            "sample_count": len(json.loads(eval_path.read_text(encoding="utf-8"))),
            "field_support": _field_support(eval_path),
            "variants": {},
        }
        for variant_name, events in variants.items():
            dataset_entry["variants"][variant_name] = {
                "macro": evaluate_extraction(events, eval_path),
                "micro": evaluate_extraction_micro(events, eval_path),
            }

        dataset_entry["regex_to_gliner_changes"] = summarize_variant_changes(
            regex_events,
            gliner_events,
            eval_path,
        )
        report["datasets"][dataset_key] = dataset_entry

    full_gliner_events: List[Dict[str, Any]]
    if use_cached_full_gliner and config.paths.extraction_results_file.exists():
        extraction_payload = json.loads(config.paths.extraction_results_file.read_text(encoding="utf-8"))
        full_gliner_events = list(extraction_payload.get("events", []))
        report["full_gliner_source"] = "cached_extraction_results"
    else:
        full_gliner_events = _build_events_for_variant(config, documents, variant="enhanced")
        report["full_gliner_source"] = "fresh_rebuild"

    if include_full_compare:
        full_regex_events = _build_events_for_variant(
            config,
            documents,
            variant="enhanced",
            disable_gliner=True,
        )
        report["full_dataset_regex_to_gliner"] = summarize_full_variant_differences(
            full_regex_events,
            full_gliner_events,
        )
    else:
        report["full_dataset_regex_to_gliner"] = {
            "skipped": True,
            "reason": "full compare disabled",
        }

    report["gliner_unknown_analysis"] = analyze_gliner_unknowns(full_gliner_events)
    return report


def render_eval_diagnostic_markdown(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("# IE Evaluation Diagnostic Report")
    lines.append("")
    lines.append(f"- Generated at: {report.get('generated_at')}")
    lines.append(f"- Primary eval set: {Path(report.get('primary_eval_path', '')).name}")
    if report.get("secondary_eval_path"):
        lines.append(f"- Secondary eval set: {Path(report['secondary_eval_path']).name}")
    lines.append(f"- Full GLiNER source: {report.get('full_gliner_source', 'unknown')}")
    lines.append("")

    for dataset_name, dataset in report.get("datasets", {}).items():
        lines.append(f"## {dataset_name}")
        lines.append("")
        lines.append(f"- Samples: {dataset.get('sample_count', 0)}")
        lines.append(f"- Field support: {dataset.get('field_support', {})}")
        lines.append("")
        lines.append("| Variant | Macro P | Macro R | Macro F1 | Micro P | Micro R | Micro F1 | Matched docs |")
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for variant_name, variant_report in dataset.get("variants", {}).items():
            macro = variant_report["macro"]["overall"]
            micro = variant_report["micro"]["overall"]
            matched_docs = variant_report["macro"]["matched_documents"]
            lines.append(
                f"| {variant_name} | {macro['precision']:.4f} | {macro['recall']:.4f} | {macro['f1']:.4f} | "
                f"{micro['precision']:.4f} | {micro['recall']:.4f} | {micro['f1']:.4f} | {matched_docs} |"
            )
        lines.append("")

        changes = dataset.get("regex_to_gliner_changes", {})
        lines.append(
            f"- Regex -> GLiNER changed {changes.get('changed_skill_count', 0)} skills / "
            f"{changes.get('changed_field_count', 0)} skill-field pairs."
        )
        lines.append(
            f"- Gain field-cases: {changes.get('gain_field_cases', 0)}, "
            f"hurt field-cases: {changes.get('hurt_field_cases', 0)}, "
            f"same field-cases: {changes.get('same_field_cases', 0)}."
        )
        lines.append("")

    full_diff = report.get("full_dataset_regex_to_gliner", {})
    lines.append("## Full Dataset Regex vs GLiNER")
    lines.append("")
    if full_diff.get("skipped"):
        lines.append(f"- Skipped: {full_diff.get('reason', 'n/a')}")
    else:
        lines.append(
            f"- Changed skills after final normalization: {full_diff.get('changed_skill_count', 0)}"
        )
        lines.append(f"- Field counts: {full_diff.get('field_counts', {})}")
    lines.append("")

    unknowns = report.get("gliner_unknown_analysis", {})
    lines.append("## GLiNER Unknowns")
    lines.append("")
    lines.append(f"- Total gliner_unknown evidence items: {unknowns.get('total_unknown', 0)}")
    lines.append(f"- Field counts: {unknowns.get('field_unknown_counts', {})}")
    lines.append("")
    lines.append("| Reason | Count |")
    lines.append("| --- | ---: |")
    for item in unknowns.get("global_reason_distribution", []):
        lines.append(f"| {item['reason']} | {item['count']} |")
    lines.append("")
    lines.append("### Recommended Vocabulary / Alias Fixes")
    lines.append("")
    lines.append("| Field | Value | Count | Suggested action |")
    lines.append("| --- | --- | ---: | --- |")
    for item in unknowns.get("recommendations", [])[:15]:
        lines.append(
            f"| {item['field']} | {item['value']} | {item['count']} | {item['suggested_action']} |"
        )
    lines.append("")
    return "\n".join(lines)
