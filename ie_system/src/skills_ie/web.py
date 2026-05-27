"""IE 抽取系统的 Flask 页面与 API。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from flask import Flask, jsonify, render_template, request

from .config import IEConfig, load_config
from .extractor import SkillsIESystem
from .evaluation import (
    compute_manual_metrics,
    evaluate_extraction,
    load_manual_judgments,
    save_manual_judgment,
)
from .state import load_json


def create_app(config_path: Path | None = None) -> Flask:
    """创建 IE Web 应用并注册页面与 API 路由。"""
    config = load_config(config_path)
    app = Flask(__name__, template_folder="templates")

    ie = SkillsIESystem(config)
    ie.load_data()
    ie.extract_all()

    @app.get("/")
    def index():
        query = request.args.get("q", "").strip()
        field = request.args.get("field", "").strip() or None
        top_k = request.args.get("top_k", "10").strip()
        try:
            top_k_value = max(1, min(int(top_k), 50))
        except ValueError:
            top_k_value = 10

        results = ie.search_extractions(query, field=field, top_k=top_k_value) if query else []

        # 抽取报告提供字段覆盖率、值分布和证据统计，是页面概览的重要数据源。
        report = ie.generate_report()

        manual_data = load_manual_judgments(config)
        manual_metrics = manual_data.get("summary", {})

        auto_eval = {}
        gt_path = config.resolve_eval_path(None)
        if gt_path.exists():
            auto_eval = evaluate_extraction(ie.extraction_results, gt_path)

        return render_template(
            "ie_search.html",
            query=query,
            field=field or "",
            top_k=top_k_value,
            results=results,
            report=report,
            manual_metrics=manual_metrics,
            auto_eval=auto_eval,
            total_docs=len(ie.documents),
            total_extractions=len(ie.extraction_results),
        )

    @app.get("/api/extract")
    def api_extract():
        text = request.args.get("text", "").strip()
        if not text:
            return jsonify({"error": "missing text parameter"}), 400
        result = ie.extract_debug_payload(text)
        return jsonify(result)

    @app.get("/api/search")
    def api_search():
        query = request.args.get("q", "").strip()
        field = request.args.get("field", "").strip() or None
        top_k = request.args.get("top_k", "10").strip()
        try:
            top_k_value = max(1, min(int(top_k), 50))
        except ValueError:
            top_k_value = 10

        results = ie.search_extractions(query, field=field, top_k=top_k_value) if query else []
        return jsonify({
            "query": query,
            "field": field,
            "top_k": top_k_value,
            "result_count": len(results),
            "results": results,
        })

    @app.post("/api/judge")
    def api_judge():
        """接收一条人工抽取判断。"""
        body = request.get_json(silent=True) or {}
        skill_name = body.get("skill_name", "").strip()
        field = body.get("field", "").strip()
        label = body.get("label", "").strip()
        value = body.get("value", "").strip()

        if not skill_name or not field or label not in ("correct", "incorrect", "partial"):
            return jsonify({"ok": False, "error": "invalid input"}), 400

        summary = save_manual_judgment(config, skill_name, field, label, value)
        return jsonify({"ok": True, "summary": summary})

    @app.get("/api/report")
    def api_report():
        return jsonify(ie.generate_report())

    @app.get("/healthz")
    def healthz():
        return jsonify({
            "ok": True,
            "document_count": len(ie.documents),
            "extraction_count": len(ie.extraction_results),
        })

    return app


def serve_web(
    config_path: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 5001,
    debug: bool = False,
) -> None:
    """启动 IE Web 服务。"""
    app = create_app(config_path)
    app.run(host=host, port=port, debug=debug)
