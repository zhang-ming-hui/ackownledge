"""
IE 系统命令行入口。

提供从终端操作 IE 子系统的完整命令集。
子命令体系：

  extract      — 对全量数据集执行抽取并保存结果
  extract-one  — 对单条文本执行抽取（调试用）
  search       — 搜索已抽取结果
  evaluate     — 对抽取结果做自动评估（对比 ground truth）
  compare      — 对比 baseline vs enhanced 变体
  report       — 生成并打印抽取报告 JSON
  serve-web    — 启动 Web UI 服务

所有子命令共享 --config 参数（默认 configs/ie_config.json）。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, load_config
from .evaluation import (
    compare_extraction_variants,
    evaluate_extraction,
    print_evaluation_report,
    save_text_atomic,
    render_variant_comparison_markdown,
    print_variant_comparison,
)
from .extractor import SkillsIESystem, print_extraction_results
from .state import save_json_atomic, utc_now_iso
from .web import serve_web


def _print_json(payload: object) -> None:
    """
    按当前终端编码安全打印 JSON。
    
    自动处理终端编码问题（如 Windows GBK 终端），
    非编码字符用 replace 策略替换，避免 UnicodeEncodeError。
    """
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    encoding = sys.stdout.encoding or "utf-8"
    safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    print(safe_text)


def _summarize_events(events):
    """
    从事件列表中汇总覆盖率与证据统计。
    
    用于 compare 命令生成变体汇总，
    和 cli.py 中的同名函数机制相同。
    汇总信息包括：
      - 信息点数量分布
      - 字段覆盖率
      - 证据来源分布（rule_source 统计）
      - 每条证据的抽样示例
    """
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
    field_samples = {field: [] for field in field_sources}
    global_sources = Counter()

    for event in events:
        info_point_distribution[event.get("info_point_count", 0)] += 1
        extraction = event.get("extraction", {})
        evidence_map = extraction.get("evidence", {}) if isinstance(extraction, dict) else {}
        for field in [
            "platforms",
            "languages",
            "action_types",
            "target_domains",
            "output_formats",
            "metrics",
        ]:
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
                # 每个字段取最多 2 条证据样本
                if len(field_samples[field]) < 2:
                    sample = evidence_items[0]
                    field_samples[field].append(
                        {
                            "skill_name": event.get("skill_name", ""),
                            "skill_id": event.get("skill_id", ""),
                            "field": sample.get("field", field),
                            "value": sample.get("value", ""),
                            "rule_source": sample.get("rule_source", ""),
                            "pattern_source": sample.get("pattern_source", ""),
                            "matched_text": sample.get("matched_text", ""),
                            "context": sample.get("context", ""),
                        }
                    )

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
                "samples": field_samples[field],
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
        "documents_with_all_fields": sum(
            1 for event in events if event.get("info_point_count", 0) >= 5
        ),
        "documents_with_no_extraction": sum(
            1 for event in events if event.get("info_point_count", 0) == 0
        ),
        "explainability": explainability,
    }


def _build_parser() -> argparse.ArgumentParser:
    """
    构建 IE CLI 的参数解析器。
    
    所有子命令共享 --config 参数。
    部分子命令支持 --variant 参数（baseline / enhanced）。
    """
    parser = argparse.ArgumentParser(description="Skills IE CLI")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Config file path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # extract: 全量抽取
    extract_parser = subparsers.add_parser("extract", help="Run extraction over the whole dataset")
    extract_parser.add_argument("--limit", type=int, default=None, help="Preview top N records")
    extract_parser.add_argument("--variant", choices=["baseline", "enhanced"], default="enhanced")

    # extract-one: 单条文本抽取（调试用）
    extract_one_parser = subparsers.add_parser("extract-one", help="Extract one input text")
    extract_one_parser.add_argument("text", help="Input text")
    extract_one_parser.add_argument("--variant", choices=["baseline", "enhanced"], default="enhanced")

    # search: 搜索已抽取结果
    search_parser = subparsers.add_parser("search", help="Search extracted events")
    search_parser.add_argument("query", help="Keyword")
    search_parser.add_argument("--field", default=None, help="Optional field filter")
    search_parser.add_argument("--top-k", type=int, default=10, help="Number of results")
    search_parser.add_argument("--variant", choices=["baseline", "enhanced"], default="enhanced")

    # evaluate: 自动评估
    eval_parser = subparsers.add_parser("evaluate", help="Run automatic evaluation")
    eval_parser.add_argument("--eval-set", default="ground_truth.json", help="Eval set name")
    eval_parser.add_argument("--variant", choices=["baseline", "enhanced"], default="enhanced")

    # compare: 变体对比
    compare_parser = subparsers.add_parser("compare", help="Compare baseline vs enhanced extraction")
    compare_parser.add_argument("--eval-set", default="ground_truth.json", help="Eval set name")

    # report: 生成报告
    report_parser = subparsers.add_parser("report", help="Generate extraction report")
    report_parser.add_argument("--variant", choices=["baseline", "enhanced"], default="enhanced")

    # serve-web: 启动 Web 界面
    web_parser = subparsers.add_parser("serve-web", help="Start the Web UI")
    web_parser.add_argument("--host", default="127.0.0.1", help="Host")
    web_parser.add_argument("--port", type=int, default=5001, help="Port")
    web_parser.add_argument("--debug", action="store_true", help="Enable debug mode")

    return parser


def _build_system(config, variant: str = "enhanced") -> SkillsIESystem:
    """
    按指定变体构建并预加载抽取系统。
    
    加载配置 → 创建 SkillsIESystem → 加载数据集 → 返回实例。
    注意此时尚未执行 extract_all()，由各子命令按需调用。
    """
    ie = SkillsIESystem(config, variant=variant)
    ie.load_data()
    return ie


def main(argv: list[str] | None = None) -> int:
    """
    CLI 主入口。
    
    解析命令行参数，按子命令分发到对应逻辑。
    返回 0 表示成功，非 0 表示失败。
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    args = _build_parser().parse_args(argv)
    config = load_config(Path(args.config))

    # ── extract ──
    if args.command == "extract":
        ie = _build_system(config, variant=args.variant)
        results = ie.extract_all()          # 全量抽取
        files = ie.save_results()           # 保存结果 + 报告 + 状态
        print(f"Extraction done: {len(results)} documents | variant={args.variant}")
        print_extraction_results(results, limit=args.limit or 10)
        print("\nSaved files:")
        for key, value in files.items():
            print(f"  {key}: {value}")
        return 0

    # ── extract-one ──
    if args.command == "extract-one":
        ie = _build_system(config, variant=args.variant)
        # 返回完整 debug 信息：extraction + evidence + gliner 跟踪
        _print_json(ie.extract_debug_payload(args.text, variant=args.variant))
        return 0

    # ── search ──
    if args.command == "search":
        ie = _build_system(config, variant=args.variant)
        ie.extract_all()
        results = ie.search_extractions(args.query, field=args.field, top_k=args.top_k)
        if results:
            print_extraction_results(results, limit=args.top_k)
        else:
            print("No matches.")
        return 0

    # ── evaluate ──
    if args.command == "evaluate":
        ie = _build_system(config, variant=args.variant)
        ie.extract_all()
        ie.save_results()
        eval_path = config.resolve_eval_path(args.eval_set)
        if not eval_path.exists():
            print(f"Evaluation set not found: {eval_path}")
            return 1
        report = evaluate_extraction(ie.extraction_results, eval_path)
        config.ensure_runtime_dirs()
        report["variant"] = args.variant
        save_json_atomic(config.paths.evaluation_report_file, report)
        save_json_atomic(config.paths.state_dir / "eval_report.json", report)
        print_evaluation_report(report)
        return 0

    # ── compare ──
    if args.command == "compare":
        baseline = _build_system(config, variant="baseline")
        enhanced = _build_system(config, variant="enhanced")
        # 两种变体分别抽取
        baseline_results = baseline.build_event_records(variant="baseline")
        enhanced_results = enhanced.build_event_records(variant="enhanced")
        eval_path = config.resolve_eval_path(args.eval_set)
        if not eval_path.exists():
            print(f"Evaluation set not found: {eval_path}")
            return 1
        report = compare_extraction_variants(baseline_results, enhanced_results, eval_path)
        config.ensure_runtime_dirs()
        report["generated_at"] = report.get("generated_at") or utc_now_iso()
        report["baseline_summary"] = _summarize_events(baseline_results)
        report["enhanced_summary"] = _summarize_events(enhanced_results)
        save_json_atomic(config.paths.comparison_report_file, report)
        markdown = render_variant_comparison_markdown(report)
        save_text_atomic(config.paths.comparison_report_markdown_file, markdown)
        print_variant_comparison(report)
        print(f"\nSaved: {config.paths.comparison_report_file}")
        print(f"Saved: {config.paths.comparison_report_markdown_file}")
        return 0

    # ── report ──
    if args.command == "report":
        ie = _build_system(config, variant=args.variant)
        ie.extract_all()
        report = ie.generate_report()
        report["variant"] = args.variant
        ie.save_results()
        _print_json(report)
        return 0

    # ── serve-web ──
    if args.command == "serve-web":
        serve_web(config_path=Path(args.config), host=args.host, port=args.port, debug=args.debug)
        return 0

    return 1
