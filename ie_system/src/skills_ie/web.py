"""
Flask UI and APIs for the IE system workbench.

The workbench supports multiple extraction variants and an optional
remote-LLM capability summary for each skill detail page.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from threading import Lock
from typing import Any, Dict

from flask import Flask, jsonify, render_template, request

from .config import load_config
from .evaluation import evaluate_extraction, load_manual_judgments, save_manual_judgment
from .extractor import EXTRACTED_FIELDS, SkillsIESystem
from .remote_llm import call_openai_compatible_json

SUPPORTED_VARIANTS = ("baseline", "enhanced", "api")
DEFAULT_VARIANT = "enhanced"
VARIANT_LABELS = {
    "baseline": "Baseline",
    "enhanced": "Enhanced",
    "api": "API",
}
VARIANT_DESCRIPTIONS = {
    "baseline": "Exact keyword rules plus metric regex.",
    "enhanced": "Rules plus GLiNER-assisted extraction.",
    "api": "Remote LLM extraction with JSON schema control.",
}


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


def _normalize_summary_payload(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, list):
        if payload and isinstance(payload[0], dict):
            payload = payload[0]
        else:
            payload = {
                "summary": "",
                "highlights": [str(item).strip() for item in payload if str(item).strip()],
            }
    elif isinstance(payload, str):
        payload = {"summary": payload, "highlights": []}
    elif not isinstance(payload, dict):
        payload = {"summary": "", "highlights": []}
    summary = str(payload.get("summary", "")).strip()
    highlights_raw = payload.get("highlights", [])
    highlights = []
    if isinstance(highlights_raw, list):
        for item in highlights_raw:
            text = str(item).strip()
            if text and text not in highlights:
                highlights.append(text)
    return {
        "available": bool(summary or highlights),
        "summary": summary,
        "highlights": highlights[:4],
    }


def _primary_remote_model_name(model_value: str) -> str:
    return str(model_value).split(",")[0].strip()


def _parse_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def create_app(config_path: Path | None = None) -> Flask:
    config = load_config(config_path)
    app = Flask(__name__, template_folder="templates")

    bootstrap_ie = SkillsIESystem(config, variant=DEFAULT_VARIANT)
    bootstrap_ie.load_data()
    documents = bootstrap_ie.documents
    gt_path = config.resolve_eval_path(None)

    variant_cache: Dict[str, Dict[str, Any]] = {}
    variant_lock = Lock()
    api_summary_cache: Dict[tuple[str, str], Dict[str, Any]] = {}
    api_summary_lock = Lock()

    def variant_enabled(variant: str) -> bool:
        return variant != "api" or config.remote_llm.enabled

    def list_available_variants() -> list[Dict[str, Any]]:
        return [
            {
                "id": variant,
                "label": VARIANT_LABELS[variant],
                "description": VARIANT_DESCRIPTIONS[variant],
                "enabled": variant_enabled(variant),
                "is_remote": variant == "api",
            }
            for variant in SUPPORTED_VARIANTS
        ]

    def normalize_variant(variant: str | None) -> str:
        value = (variant or "").strip() or DEFAULT_VARIANT
        if value not in SUPPORTED_VARIANTS:
            raise ValueError(f"unsupported variant: {value}")
        if not variant_enabled(value):
            raise RuntimeError(f"variant unavailable: {value}")
        return value

    def get_manual_metrics() -> Dict[str, Any]:
        manual_data = load_manual_judgments(config)
        return manual_data.get("summary", {})

    def build_variant_bundle(variant: str) -> Dict[str, Any]:
        with variant_lock:
            cached = variant_cache.get(variant)
        if cached is not None:
            return cached

        ie = SkillsIESystem(config, variant=variant)
        ie.load_data()
        ie.load_or_extract_results(persist_cache=True)

        bundle = {
            "variant": variant,
            "ie": ie,
            "report": ie.generate_report(),
            "auto_eval": evaluate_extraction(ie.extraction_results, gt_path) if gt_path.exists() else {},
            "events_by_skill_id": {
                str(event.get("skill_id") or ""): event
                for event in ie.extraction_results
                if str(event.get("skill_id") or "")
            },
            "docs_by_skill_id": {
                str(doc.get("skill_id") or ""): doc
                for doc in ie.documents
                if str(doc.get("skill_id") or "")
            },
        }

        with variant_lock:
            variant_cache.setdefault(variant, bundle)
            return variant_cache[variant]

    def store_variant_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
        with variant_lock:
            variant_cache[bundle["variant"]] = bundle
            return variant_cache[bundle["variant"]]

    def get_variant_bundle(variant: str) -> Dict[str, Any]:
        normalized = normalize_variant(variant)
        return build_variant_bundle(normalized)

    def rebuild_variant_bundle(ie: SkillsIESystem, variant: str) -> Dict[str, Any]:
        bundle = {
            "variant": variant,
            "ie": ie,
            "report": ie.generate_report(),
            "auto_eval": evaluate_extraction(ie.extraction_results, gt_path) if gt_path.exists() else {},
            "events_by_skill_id": {
                str(event.get("skill_id") or ""): event
                for event in ie.extraction_results
                if str(event.get("skill_id") or "")
            },
            "docs_by_skill_id": {
                str(doc.get("skill_id") or ""): doc
                for doc in ie.documents
                if str(doc.get("skill_id") or "")
            },
        }
        return store_variant_bundle(bundle)

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

    def serialize_event_detail(bundle: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
        skill_id = str(event.get("skill_id") or "")
        doc = bundle["docs_by_skill_id"].get(skill_id, {})
        source_text = bundle["ie"].get_document_source_text(doc) if doc else ""
        return {
            **serialize_event_summary(event),
            "source_text": source_text,
            "extraction": _copy_full_extraction(event.get("extraction", {})),
        }

    def build_workbench_payload(variant: str) -> Dict[str, Any]:
        bundle = get_variant_bundle(variant)
        ie = bundle["ie"]
        return {
            "summary": {
                "variant": variant,
                "variant_label": VARIANT_LABELS[variant],
                "total_docs": len(ie.documents),
                "total_extractions": len(ie.extraction_results),
                "api_description_enabled": bool(config.remote_llm.enabled),
            },
            "available_variants": list_available_variants(),
            "events": [serialize_event_summary(event) for event in ie.extraction_results],
            "report": bundle["report"],
            "manual_metrics": get_manual_metrics(),
            "auto_eval": bundle["auto_eval"],
        }

    def build_api_summary_prompt(detail: Dict[str, Any]) -> str:
        extraction_json = json.dumps(
            _copy_extraction_values(detail.get("extraction", {})),
            ensure_ascii=False,
            indent=2,
        )
        source_text = str(detail.get("source_text", "")).strip()[:900]
        description_preview = str(detail.get("description_preview", "")).strip()
        return (
            "Summarize the following skill in Chinese and return strict JSON only.\n\n"
            "Schema:\n"
            "{\n"
            '  "summary": "...",\n'
            '  "highlights": ["...", "...", "..."]\n'
            "}\n\n"
            "Rules:\n"
            "- Stay faithful to the source text and the structured extraction hints.\n"
            "- The summary should be 1 concise Chinese sentence describing likely usage flow and capabilities.\n"
            "- Do not invent outcomes, saved files, evaluated scores, or concrete execution results.\n"
            "- Highlights should be short Chinese fragments, each under 18 characters.\n"
            "- Prefer short output; do not repeat the skill name excessively.\n"
            "- Return JSON only.\n\n"
            f"Skill name: {detail.get('skill_name', '')}\n"
            f"Owner: {detail.get('owner', '')}\n"
            f"Category: {detail.get('category', '')}\n"
            f"Extraction variant: {detail.get('variant', '')}\n"
            f"Description preview: {description_preview}\n\n"
            "Structured extraction hints:\n"
            f"{extraction_json}\n\n"
            "Source text:\n"
            f"{source_text}"
        )

    def get_api_summary(bundle: Dict[str, Any], skill_id: str) -> Dict[str, Any]:
        cache_key = (bundle["variant"], skill_id)
        with api_summary_lock:
            cached = api_summary_cache.get(cache_key)
        if cached is not None:
            return cached

        if not config.remote_llm.enabled:
            payload = {
                "available": False,
                "summary": "",
                "highlights": [],
                "error": "remote_llm disabled in config",
                "model": _primary_remote_model_name(config.remote_llm.model),
            }
            with api_summary_lock:
                api_summary_cache.setdefault(cache_key, payload)
                return api_summary_cache[cache_key]

        event = bundle["events_by_skill_id"].get(skill_id)
        if not event:
            raise KeyError(skill_id)

        detail = serialize_event_detail(bundle, event)
        summary_config = replace(
            config.remote_llm,
            system_prompt="You are a skill capability summarization engine. Return strict JSON only.",
            temperature=0.0,
            max_output_tokens=min(config.remote_llm.max_output_tokens, 160),
            timeout_seconds=min(config.remote_llm.timeout_seconds, 25),
        )
        prompt = build_api_summary_prompt(detail)
        try:
            raw_payload = call_openai_compatible_json(summary_config, prompt)
            normalized = _normalize_summary_payload(raw_payload)
            normalized["model"] = _primary_remote_model_name(summary_config.model)
            if not normalized["available"]:
                normalized["error"] = "empty summary payload"
        except Exception as exc:
            normalized = {
                "available": False,
                "summary": "",
                "highlights": [],
                "error": str(exc),
                "model": _primary_remote_model_name(summary_config.model),
            }

        with api_summary_lock:
            api_summary_cache.setdefault(cache_key, normalized)
            return api_summary_cache[cache_key]

    def invalidate_api_summary_cache(variant: str, skill_id: str | None = None) -> None:
        with api_summary_lock:
            if skill_id is not None:
                api_summary_cache.pop((variant, skill_id), None)
                return
            to_remove = [key for key in api_summary_cache if key[0] == variant]
            for key in to_remove:
                api_summary_cache.pop(key, None)

    @app.get("/")
    def index():
        initial_variant = request.args.get("variant", "").strip() or DEFAULT_VARIANT
        if initial_variant not in SUPPORTED_VARIANTS:
            initial_variant = DEFAULT_VARIANT
        if initial_variant == "api" and not config.remote_llm.enabled:
            initial_variant = DEFAULT_VARIANT
        return render_template(
            "ie_search.html",
            initial_query=request.args.get("q", "").strip(),
            initial_skill_id=request.args.get("skill_id", "").strip(),
            initial_variant=initial_variant,
        )

    @app.get("/api/workbench")
    def api_workbench():
        try:
            variant = normalize_variant(request.args.get("variant"))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(build_workbench_payload(variant))

    @app.get("/api/events/<skill_id>")
    def api_event_detail(skill_id: str):
        try:
            variant = normalize_variant(request.args.get("variant"))
            bundle = get_variant_bundle(variant)
        except (ValueError, RuntimeError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        event = bundle["events_by_skill_id"].get(skill_id)
        if not event:
            return jsonify({"ok": False, "error": "skill not found"}), 404
        return jsonify({"ok": True, "event": serialize_event_detail(bundle, event)})

    @app.get("/api/describe/<skill_id>")
    def api_describe(skill_id: str):
        try:
            variant = normalize_variant(request.args.get("variant"))
            bundle = get_variant_bundle(variant)
        except (ValueError, RuntimeError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        if skill_id not in bundle["events_by_skill_id"]:
            return jsonify({"ok": False, "error": "skill not found"}), 404
        return jsonify({"ok": True, "description": get_api_summary(bundle, skill_id)})

    @app.get("/api/extract")
    def api_extract():
        text = request.args.get("text", "").strip()
        variant = request.args.get("variant", "").strip() or DEFAULT_VARIANT
        if not text:
            return jsonify({"error": "missing text parameter"}), 400
        try:
            bundle = get_variant_bundle(variant)
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(bundle["ie"].extract_debug_payload(text, variant=variant))

    @app.post("/api/extract-all")
    def api_extract_all():
        body = request.get_json(silent=True) or {}
        try:
            variant = normalize_variant(body.get("variant") or request.args.get("variant"))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        ie = SkillsIESystem(config, variant=variant)
        ie.load_data()
        ie.extract_all()
        files = ie.save_results()
        bundle = rebuild_variant_bundle(ie, variant)
        invalidate_api_summary_cache(variant)
        return jsonify(
            {
                "ok": True,
                "mode": "full_reextract",
                "variant": variant,
                "document_count": len(ie.documents),
                "extraction_count": len(ie.extraction_results),
                "files": files,
                "report": bundle["report"],
                "auto_eval": bundle["auto_eval"],
            }
        )

    @app.post("/api/events/<skill_id>/reextract")
    def api_reextract_event(skill_id: str):
        body = request.get_json(silent=True) or {}
        try:
            variant = normalize_variant(body.get("variant") or request.args.get("variant"))
            bundle = get_variant_bundle(variant)
        except (ValueError, RuntimeError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        persist_cache = _parse_bool(body.get("persist_cache", request.args.get("persist_cache")), default=True)
        include_debug = _parse_bool(body.get("include_debug", request.args.get("include_debug")), default=True)
        try:
            event, debug_payload = bundle["ie"].reextract_document_by_skill_id(
                skill_id,
                persist_cache=persist_cache,
                collect_debug=include_debug,
            )
        except KeyError:
            return jsonify({"ok": False, "error": "skill not found"}), 404

        bundle = rebuild_variant_bundle(bundle["ie"], variant)
        invalidate_api_summary_cache(variant, skill_id=skill_id)
        payload = {
            "ok": True,
            "mode": "single_reextract",
            "variant": variant,
            "persist_cache": persist_cache,
            "event": serialize_event_detail(bundle, event),
            "report": bundle["report"],
        }
        if include_debug:
            payload["debug"] = debug_payload
        return jsonify(payload)

    @app.get("/api/search")
    def api_search():
        query = request.args.get("q", "").strip()
        field = request.args.get("field", "").strip() or None
        variant = request.args.get("variant", "").strip() or DEFAULT_VARIANT
        top_k = request.args.get("top_k", "10").strip()
        try:
            top_k_value = max(1, min(int(top_k), 50))
        except ValueError:
            top_k_value = 10
        try:
            bundle = get_variant_bundle(variant)
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400

        results = bundle["ie"].search_extractions(query, field=field, top_k=top_k_value) if query else []
        return jsonify(
            {
                "query": query,
                "field": field,
                "variant": variant,
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
        variant = body.get("variant", "").strip()

        if not skill_name or not field or label not in ("correct", "incorrect", "partial"):
            return jsonify({"ok": False, "error": "invalid input"}), 400

        summary = save_manual_judgment(
            config,
            skill_name=skill_name,
            field=field,
            label=label,
            value=value,
            variant=variant,
        )
        return jsonify({"ok": True, "summary": summary})

    @app.get("/api/report")
    def api_report():
        try:
            variant = normalize_variant(request.args.get("variant"))
        except (ValueError, RuntimeError) as exc:
            return jsonify({"error": str(exc)}), 400
        return jsonify(get_variant_bundle(variant)["report"])

    @app.get("/healthz")
    def healthz():
        with variant_lock:
            cached_variants = sorted(variant_cache.keys())
        return jsonify(
            {
                "ok": True,
                "document_count": len(documents),
                "default_variant": DEFAULT_VARIANT,
                "available_variants": list_available_variants(),
                "cached_variants": cached_variants,
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
