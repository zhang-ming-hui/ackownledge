from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .comparison import compare_retrieval_modes, print_comparison_report, render_comparison_markdown
from .config import DEFAULT_CONFIG_PATH, load_config
from .cycle import run_cycle
from .data_health import save_data_health_report
from .engine import SkillsIRSystem, print_results
from .evaluation import evaluate_queries, print_evaluation_report
from .ingest import run_ingest
from .review import build_live_benchmark_review, review_runtime_snapshot
from .state import load_json, save_json_atomic, utc_now_iso
from .web import serve_web


def _print_json(payload: object) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    encoding = sys.stdout.encoding or "utf-8"
    safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    print(safe_text)


def interactive_mode(engine: SkillsIRSystem, top_k: int) -> None:
    print("Skills IR interactive mode. Submit an empty line to exit.")
    while True:
        query = input("\nQuery: ").strip()
        if not query:
            print("Bye.")
            return
        print_results(query, engine.search(query, top_k=top_k))


def _build_subcommand_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Skills IR project CLI")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Config file path")
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_index_parser = subparsers.add_parser("build-index", help="Build or reuse the index")
    build_index_parser.add_argument("--force", action="store_true", help="Force a rebuild")

    search_parser = subparsers.add_parser("search", help="Run a search query")
    search_parser.add_argument("query", help="Natural language query")
    search_parser.add_argument("--top-k", type=int, default=None, help="Number of results")

    evaluate_parser = subparsers.add_parser("evaluate", help="Run offline evaluation")
    evaluate_parser.add_argument("--eval-set", default=None, help="Evaluation set name or path")
    evaluate_parser.add_argument("--top-k", type=int, default=None, help="Top-k value")

    compare_parser = subparsers.add_parser("compare-modes", help="Compare tfidf / bm25 / hybrid")
    compare_parser.add_argument("--eval-set", action="append", default=None, help="Evaluation set name or path")
    compare_parser.add_argument("--top-k", type=int, default=None, help="Top-k value")

    ingest_parser = subparsers.add_parser("ingest", help="Run data ingestion")
    ingest_parser.add_argument("--target-count", type=int, default=None, help="Target record count")
    ingest_parser.add_argument("--sleep-seconds", type=float, default=None, help="Crawl interval")
    ingest_parser.add_argument("--headless", action="store_true", help="Use headless browser")

    subparsers.add_parser("data-health", help="Generate data health report")
    subparsers.add_parser("normalize-data", help="Normalize current dataset outputs")

    refresh_parser = subparsers.add_parser("refresh-data", help="Refresh incomplete records")
    refresh_parser.add_argument("--limit", type=int, default=None, help="Max records to refresh")
    refresh_parser.add_argument("--sleep-seconds", type=float, default=0.5, help="Refresh interval")

    review_parser = subparsers.add_parser("review-system", help="Run runtime and benchmark review")
    review_parser.add_argument("--top-k", type=int, default=None, help="Top-k value")

    cycle_parser = subparsers.add_parser("run-cycle", help="Run one autonomous cycle")
    cycle_parser.add_argument("--top-k", type=int, default=None, help="Top-k value")
    cycle_parser.add_argument("--eval-set", default=None, help="Evaluation set name or path")
    cycle_parser.add_argument("--run-ingest", action="store_true", help="Include ingest step")
    cycle_parser.add_argument("--headless", action="store_true", help="Use headless browser for ingest")

    serve_web_parser = subparsers.add_parser("serve-web", help="Start the web UI")
    serve_web_parser.add_argument("--host", default="127.0.0.1", help="Host")
    serve_web_parser.add_argument("--port", type=int, default=5000, help="Port")
    serve_web_parser.add_argument("--debug", action="store_true", help="Enable Flask debug mode")

    report_parser = subparsers.add_parser("report", help="Read a saved report")
    report_parser.add_argument(
        "--kind",
        choices=["state", "cycle", "metrics", "failures", "data-health", "search", "review", "comparison"],
        default="state",
        help="Report kind",
    )
    return parser


def _build_legacy_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Legacy IR CLI")
    parser.add_argument("query", nargs="?", default="", help="Natural language query")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Config file path")
    parser.add_argument("--top-k", type=int, default=None, help="Number of results")
    parser.add_argument("--rebuild", action="store_true", help="Force rebuild the local index")
    parser.add_argument("--interactive", action="store_true", help="Enter interactive mode")
    parser.add_argument("--evaluate", action="store_true", help="Run default evaluation set")
    return parser


def _is_subcommand_mode(argv: list[str]) -> bool:
    if not argv:
        return False

    known = {
        "build-index",
        "search",
        "evaluate",
        "compare-modes",
        "ingest",
        "data-health",
        "normalize-data",
        "refresh-data",
        "review-system",
        "run-cycle",
        "serve-web",
        "report",
    }
    skip_next = False
    for token in argv:
        if skip_next:
            skip_next = False
            continue
        if token == "--config":
            skip_next = True
            continue
        if token.startswith("-"):
            continue
        return token in known
    return False


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv in (["-h"], ["--help"]):
        parser = _build_subcommand_parser()
        parser.print_help()
        print(
            "\nLegacy compatibility:\n"
            "  python skills_ir_system.py \"query text\" [--top-k 5]\n"
            "  python skills_ir_system.py --interactive\n"
            "  python skills_ir_system.py --evaluate"
        )
        return 0

    if _is_subcommand_mode(argv):
        parser = _build_subcommand_parser()
        args = parser.parse_args(argv)
        config = load_config(Path(args.config))

        if args.command == "build-index":
            engine = SkillsIRSystem(config)
            summary = engine.build_index() if args.force else (engine.load_or_build() or engine.summary())
            if summary is None:
                summary = engine.summary()
            print(f"Index ready: {summary}")
            return 0

        if args.command == "search":
            engine = SkillsIRSystem(config)
            engine.load_or_build()
            results = engine.search(args.query, top_k=args.top_k)
            save_json_atomic(
                config.paths.search_results_file,
                {
                    "generated_at": utc_now_iso(),
                    "query": args.query,
                    "top_k": args.top_k or config.default_top_k,
                    "mode": "hybrid",
                    "result_count": len(results),
                    "index_summary": engine.summary(),
                    "results": results,
                },
            )
            print_results(args.query, results)
            return 0

        if args.command == "evaluate":
            engine = SkillsIRSystem(config)
            engine.load_or_build()
            report = evaluate_queries(
                engine,
                eval_path=config.resolve_eval_path(args.eval_set),
                top_k=args.top_k or config.default_top_k,
            )
            config.ensure_runtime_dirs()
            save_json_atomic(config.paths.metrics_report_file, report)
            save_json_atomic(
                config.paths.failure_buckets_file,
                {
                    "generated_at": utc_now_iso(),
                    "eval_path": report["eval_path"],
                    "top_k": report["top_k"],
                    "failure_buckets": report["failure_buckets"],
                },
            )
            print_evaluation_report(report)
            return 0

        if args.command == "compare-modes":
            engine = SkillsIRSystem(config)
            engine.load_or_build()
            eval_names = args.eval_set or [config.default_eval_set, "multilingual.json"]
            eval_paths = [config.resolve_eval_path(name) for name in eval_names]
            report = compare_retrieval_modes(
                engine,
                eval_paths=eval_paths,
                top_k=args.top_k or config.default_top_k,
            )
            report["generated_at"] = utc_now_iso()
            markdown = render_comparison_markdown(report, title="IR Algorithm Comparison Report")
            config.ensure_runtime_dirs()
            save_json_atomic(config.paths.comparison_report_file, report)
            config.paths.comparison_report_markdown_file.parent.mkdir(parents=True, exist_ok=True)
            config.paths.comparison_report_markdown_file.write_text(markdown, encoding="utf-8")
            print_comparison_report(report)
            print(f"\nSaved: {config.paths.comparison_report_file}")
            print(f"Saved: {config.paths.comparison_report_markdown_file}")
            return 0

        if args.command == "ingest":
            summary = run_ingest(
                config,
                target_count=args.target_count,
                sleep_seconds=args.sleep_seconds,
                headless=args.headless,
            )
            _print_json(summary)
            return 0

        if args.command == "data-health":
            report = save_data_health_report(config)
            _print_json(report)
            return 0

        if args.command == "normalize-data":
            from paqu import normalize_existing_outputs

            _print_json(normalize_existing_outputs())
            return 0

        if args.command == "refresh-data":
            from paqu import refresh_incomplete_records

            _print_json(
                refresh_incomplete_records(limit=args.limit, sleep_seconds=args.sleep_seconds)
            )
            return 0

        if args.command == "review-system":
            engine = SkillsIRSystem(config)
            engine.load_or_build()
            payload = {
                "generated_at": utc_now_iso(),
                "runtime_review": review_runtime_snapshot(config),
                "live_benchmarks": build_live_benchmark_review(
                    config,
                    engine,
                    eval_names=[config.default_eval_set, "multilingual.json"],
                    top_k=args.top_k or config.default_top_k,
                ),
            }
            save_json_atomic(config.paths.review_report_file, payload)
            _print_json(payload)
            return 0

        if args.command == "run-cycle":
            _print_json(
                run_cycle(
                    config,
                    top_k=args.top_k,
                    eval_set=args.eval_set,
                    run_ingest_step=args.run_ingest,
                    headless=args.headless,
                )
            )
            return 0

        if args.command == "serve-web":
            serve_web(config_path=Path(args.config), host=args.host, port=args.port, debug=args.debug)
            return 0

        if args.command == "report":
            path_map = {
                "state": config.paths.project_state_file,
                "cycle": config.paths.cycle_report_file,
                "metrics": config.paths.metrics_report_file,
                "failures": config.paths.failure_buckets_file,
                "data-health": config.paths.data_health_report_file,
                "search": config.paths.search_results_file,
                "review": config.paths.review_report_file,
                "comparison": config.paths.comparison_report_file,
            }
            _print_json(load_json(path_map[args.kind], default={}))
            return 0

        return 1

    parser = _build_legacy_parser()
    args = parser.parse_args(argv)
    config = load_config(Path(args.config))
    engine = SkillsIRSystem(config)

    if args.rebuild:
        engine.build_index()
    else:
        engine.load_or_build()

    if args.interactive:
        interactive_mode(engine, top_k=args.top_k or config.default_top_k)
        return 0

    if args.evaluate:
        report = evaluate_queries(
            engine,
            eval_path=config.resolve_eval_path(None),
            top_k=args.top_k or config.default_top_k,
        )
        config.ensure_runtime_dirs()
        save_json_atomic(config.paths.metrics_report_file, report)
        save_json_atomic(
            config.paths.failure_buckets_file,
            {
                "generated_at": utc_now_iso(),
                "eval_path": report["eval_path"],
                "top_k": report["top_k"],
                "failure_buckets": report["failure_buckets"],
            },
        )
        print_evaluation_report(report)
        return 0

    query = args.query.strip()
    if not query:
        print("Provide a query, or use --interactive / --evaluate.")
        return 0

    print_results(query, engine.search(query, top_k=args.top_k or config.default_top_k))
    return 0
