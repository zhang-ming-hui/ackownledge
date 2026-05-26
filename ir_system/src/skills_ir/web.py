from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from flask import Flask, jsonify, render_template, request

from .config import IRConfig, load_config
from .engine import SkillsIRSystem
from .review import build_live_benchmark_review, review_query_results, review_runtime_snapshot
from .state import load_json, save_json_atomic, utc_now_iso


def _load_eval_matches(config: IRConfig, query: str, top_k: int) -> list[Dict[str, Any]]:
    matches: list[Dict[str, Any]] = []
    eval_dir = config.paths.eval_dir
    if not eval_dir.exists():
        return matches

    for eval_file in sorted(eval_dir.glob("*.json")):
        try:
            payload = json.loads(eval_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for case in payload:
            if case.get("query") == query:
                matches.append(
                    {
                        "eval_file": eval_file.name,
                        "query_type": case.get("query_type", "general"),
                        "expected_skill_names": case.get("expected_skill_names", []),
                        "top_k": top_k,
                    }
                )
    return matches


def _load_manual_judgments(config: IRConfig) -> Dict[str, Any]:
    """加载人工评价结果。"""
    judgments_path = config.paths.state_dir / "manual_judgments.json"
    return load_json(judgments_path, default={"judgments": [], "summary": {}})


def _save_manual_judgments(config: IRConfig, data: Dict[str, Any]) -> None:
    """保存人工评价结果。"""
    config.ensure_runtime_dirs()
    judgments_path = config.paths.state_dir / "manual_judgments.json"
    save_json_atomic(judgments_path, data)


def _compute_manual_metrics(judgments: list[Dict[str, Any]]) -> Dict[str, Any]:
    """根据人工标注计算 P/R/F1。"""
    if not judgments:
        return {}

    queries = {}
    for j in judgments:
        q = j["query"]
        if q not in queries:
            queries[q] = {"total": 0, "relevant": 0, "partial": 0, "not_relevant": 0}
        queries[q]["total"] += 1
        label = j.get("label", "not_relevant")
        if label == "relevant":
            queries[q]["relevant"] += 1
        elif label == "partial":
            queries[q]["partial"] += 1
        else:
            queries[q]["not_relevant"] += 1

    total_results = sum(q["total"] for q in queries.values())
    total_relevant = sum(q["relevant"] for q in queries.values())
    total_partial = sum(q["partial"] for q in queries.values())

    precision = (total_relevant + 0.5 * total_partial) / total_results if total_results else 0
    query_count = len(queries)

    return {
        "query_count": query_count,
        "total_judgments": len(judgments),
        "total_relevant": total_relevant,
        "total_partial": total_partial,
        "total_not_relevant": total_results - total_relevant - total_partial,
        "precision": round(precision, 4),
        "per_query": {
            q: {
                "precision": round(
                    (v["relevant"] + 0.5 * v["partial"]) / v["total"], 4
                ) if v["total"] else 0,
                **v,
            }
            for q, v in queries.items()
        },
    }


def create_app(config_path: Path | None = None) -> Flask:
    config = load_config(config_path)
    app = Flask(__name__, template_folder="templates")
    engine = SkillsIRSystem(config)
    engine.load_or_build()

    @app.get("/")
    def index():
        query = request.args.get("q", "").strip()
        top_k = request.args.get("top_k", str(config.default_top_k)).strip()
        mode = request.args.get("mode", "hybrid").strip()
        try:
            top_k_value = max(1, min(int(top_k), 20))
        except ValueError:
            top_k_value = config.default_top_k

        results = engine.search(query, top_k=top_k_value, mode=mode) if query else []
        eval_matches = _load_eval_matches(config, query, top_k_value) if query else []
        runtime_review = review_runtime_snapshot(config)
        live_benchmarks = build_live_benchmark_review(
            config,
            engine,
            eval_names=[config.default_eval_set, "multilingual.json"],
            top_k=top_k_value,
        )
        query_review = review_query_results(query, results, eval_matches) if query else {}
        manual_data = _load_manual_judgments(config)
        manual_metrics = _compute_manual_metrics(manual_data.get("judgments", []))

        return render_template(
            "search.html",
            query=query,
            top_k=top_k_value,
            mode=mode,
            results=results,
            eval_matches=eval_matches,
            metrics=runtime_review.get("metrics_report", {}),
            failure_buckets=runtime_review.get("failure_buckets", {}).get("failure_buckets", {}),
            runtime_findings=runtime_review.get("findings", []),
            live_benchmarks=live_benchmarks,
            query_review=query_review,
            manual_metrics=manual_metrics,
        )

    @app.get("/metrics")
    def metrics():
        runtime_review = review_runtime_snapshot(config)
        live_benchmarks = build_live_benchmark_review(
            config,
            engine,
            eval_names=[config.default_eval_set, "multilingual.json"],
            top_k=config.default_top_k,
        )
        return {
            "runtime_review": runtime_review,
            "live_benchmarks": live_benchmarks,
        }

    @app.get("/api/search")
    def api_search():
        query = request.args.get("q", "").strip()
        top_k = request.args.get("top_k", str(config.default_top_k)).strip()
        mode = request.args.get("mode", "hybrid").strip()
        try:
            top_k_value = max(1, min(int(top_k), 20))
        except ValueError:
            top_k_value = config.default_top_k
        results = engine.search(query, top_k=top_k_value, mode=mode) if query else []
        return {
            "query": query,
            "top_k": top_k_value,
            "mode": mode,
            "result_count": len(results),
            "results": results,
            "eval_matches": _load_eval_matches(config, query, top_k_value) if query else [],
            "query_review": review_query_results(
                query,
                results,
                _load_eval_matches(config, query, top_k_value) if query else [],
            ) if query else {"status": "idle", "findings": []},
        }

    @app.post("/api/judge")
    def api_judge():
        """接收人工相关度评价。"""
        body = request.get_json(silent=True) or {}
        query = body.get("query", "").strip()
        skill_name = body.get("skill_name", "").strip()
        label = body.get("label", "").strip()
        rank = body.get("rank", 0)

        if not query or not skill_name or label not in ("relevant", "partial", "not_relevant"):
            return jsonify({"ok": False, "error": "invalid input"}), 400

        manual_data = _load_manual_judgments(config)
        judgments = manual_data.get("judgments", [])

        # 去重：同一 query + skill_name 只保留最新评价
        judgments = [
            j for j in judgments
            if not (j["query"] == query and j["skill_name"] == skill_name)
        ]
        judgments.append({
            "query": query,
            "skill_name": skill_name,
            "label": label,
            "rank": rank,
            "timestamp": utc_now_iso(),
        })

        manual_data["judgments"] = judgments
        manual_data["summary"] = _compute_manual_metrics(judgments)
        _save_manual_judgments(config, manual_data)

        return jsonify({"ok": True, "total_judgments": len(judgments)})

    @app.get("/api/manual-metrics")
    def api_manual_metrics():
        """返回人工评价统计。"""
        manual_data = _load_manual_judgments(config)
        return jsonify(_compute_manual_metrics(manual_data.get("judgments", [])))

    @app.get("/healthz")
    def healthz():
        return {
            "ok": True,
            "document_count": len(engine.documents),
            "index_terms": len(engine.idf),
            "bm25_terms": len(engine.bm25_idf),
        }

    return app


def serve_web(
    config_path: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 5000,
    debug: bool = False,
) -> None:
    app = create_app(config_path)
    app.run(host=host, port=port, debug=debug)
