"""
Flask UI and APIs for the IE system workbench.

The page keeps the existing single-service Flask deployment model while
exposing JSON endpoints that power a richer three-panel frontend.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from flask import Flask, jsonify, render_template, request

from .config import load_config
from .evaluation import evaluate_extraction, load_manual_judgments, save_manual_judgment
from .extractor import EXTRACTED_FIELDS, SkillsIESystem


def _copy_extraction_values(extraction: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for field in EXTRACTED_FIELDS:
        values = extraction.get(field, [])
        payload[field] = list(values) if isinstance(values, list) else []
    return payload


def _copy_full_extraction(extraction: Dict[str, Any]) -> Dict[str, Any]:
    payload = _copy_extraction_values(extraction)
    evidence_map = extraction.get("evidence", {})
    payload["evidence"] = {
        field: list(evidence_map.get(field, []) or [])
        for field in EXTRACTED_FIELDS
    }
    return payload


def create_app(config_path: Path | None = None) -> Flask:
    config = load_config(config_path)
    app = Flask(__name__, template_folder="templates")

    default_variant = "api" if config.remote_llm.enabled else "enhanced"
    ie = SkillsIESystem(config, variant=default_variant)
    ie.load_data()
    ie.extract_all()

    events_by_skill_id = {
        str(event.get("skill_id") or ""): event
        for event in ie.extraction_results
        if str(event.get("skill_id") or "")
    }
    docs_by_skill_id = {
        str(doc.get("skill_id") or ""): doc
        for doc in ie.documents
        if str(doc.get("skill_id") or "")
    }

    report = ie.generate_report()
    gt_path = config.resolve_eval_path(None)
    auto_eval = evaluate_extraction(ie.extraction_results, gt_path) if gt_path.exists() else {}

    def get_manual_metrics() -> Dict[str, Any]:
        manual_data = load_manual_judgments(config)
        return manual_data.get("summary", {})

    def serialize_event_summary(event: Dict[str, Any]) -> Dict[str, Any]:
        extraction = event.get("extraction", {})
        return {
            "skill_id": event.get("skill_id", ""),
            "skill_name": event.get("skill_name", ""),
            "owner": event.get("owner", ""),
            "category": event.get("category", ""),
            "detail_url": event.get("detail_url", ""),
            "description_preview": event.get("description_preview", ""),
            "variant": event.get("variant", ""),
            "event_summary": event.get("event_summary", ""),
            "info_point_count": event.get("info_point_count", 0),
            "evidence_count": event.get("evidence_count", 0),
            "extraction": _copy_extraction_values(extraction),
        }

    def serialize_event_detail(event: Dict[str, Any]) -> Dict[str, Any]:
        skill_id = str(event.get("skill_id") or "")
        doc = docs_by_skill_id.get(skill_id, {})
        source_text = ie.get_document_source_text(doc) if doc else ""
        return {
            **serialize_event_summary(event),
            "source_text": source_text,
            "extraction": _copy_full_extraction(event.get("extraction", {})),
        }

    def build_workbench_payload() -> Dict[str, Any]:
        return {
            "summary": {
                "variant": ie.variant,
                "total_docs": len(ie.documents),
                "total_extractions": len(ie.extraction_results),
            },
            "events": [serialize_event_summary(event) for event in ie.extraction_results],
            "report": report,
            "manual_metrics": get_manual_metrics(),
            "auto_eval": auto_eval,
        }

    @app.get("/")
    def index():
        return render_template(
            "ie_search.html",
            initial_query=request.args.get("q", "").strip(),
            initial_skill_id=request.args.get("skill_id", "").strip(),
        )

    @app.get("/api/workbench")
    def api_workbench():
        return jsonify(build_workbench_payload())

    @app.get("/api/events/<skill_id>")
    def api_event_detail(skill_id: str):
        event = events_by_skill_id.get(skill_id)
        if not event:
            return jsonify({"ok": False, "error": "skill not found"}), 404
        return jsonify({"ok": True, "event": serialize_event_detail(event)})

    @app.get("/api/extract")
    def api_extract():
        text = request.args.get("text", "").strip()
        variant = request.args.get("variant", "").strip() or ie.variant
        if not text:
            return jsonify({"error": "missing text parameter"}), 400
        return jsonify(ie.extract_debug_payload(text, variant=variant))

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
        return jsonify(
            {
                "query": query,
                "field": field,
                "top_k": top_k_value,
                "result_count": len(results),
                "results": results,
            }
        )

    @app.post("/api/judge")
    def api_judge():
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
        return jsonify(report)

    @app.get("/healthz")
    def healthz():
        return jsonify(
            {
                "ok": True,
                "document_count": len(ie.documents),
                "extraction_count": len(ie.extraction_results),
                "variant": ie.variant,
            }
        )

    return app


def serve_web(
    config_path: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 5001,
    debug: bool = False,
) -> None:
    app = create_app(config_path)
    app.run(host=host, port=port, debug=debug)
