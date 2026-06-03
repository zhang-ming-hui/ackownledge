"""统一前端入口 —— 整合 IR / IE / Multimedia 三个子系统。"""

from __future__ import annotations

from dataclasses import replace
import json
import sys
from threading import Lock
from pathlib import Path

# ── 项目根路径 ────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "ir_system" / "src"))
sys.path.insert(0, str(_PROJECT_ROOT / "ie_system" / "src"))
sys.path.insert(0, str(_PROJECT_ROOT / "multimedia_system"))

from flask import Flask, jsonify, render_template, request, send_from_directory

# ═══════════════════════════════════════════════════════════
#  子系统初始化
# ═══════════════════════════════════════════════════════════

# ── IR ────────────────────────────────────────────────────
from skills_ir.config import IRConfig, load_config as ir_load_config
from skills_ir.engine import SkillsIRSystem
from skills_ir.review import build_live_benchmark_review, review_query_results, review_runtime_snapshot
from skills_ir.state import load_json, save_json_atomic, utc_now_iso

_ir_config = ir_load_config(_PROJECT_ROOT / "ir_system" / "configs" / "ir_config.json")
_ir_engine = SkillsIRSystem(_ir_config)
_ir_engine.load_or_build()


def _load_ir_eval_matches(query: str, top_k: int) -> list:
    matches: list = []
    eval_dir = _ir_config.paths.eval_dir
    if not eval_dir.exists():
        return matches
    for eval_file in sorted(eval_dir.glob("*.json")):
        try:
            payload = json.loads(eval_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for case in payload:
            if case.get("query") == query:
                matches.append({
                    "eval_file": eval_file.name,
                    "query_type": case.get("query_type", "general"),
                    "expected_skill_names": case.get("expected_skill_names", []),
                    "top_k": top_k,
                })
    return matches


def _load_ir_manual_judgments() -> dict:
    judgments_path = _ir_config.paths.state_dir / "manual_judgments.json"
    return load_json(judgments_path, default={"judgments": [], "summary": {}})


def _save_ir_manual_judgments(data: dict) -> None:
    _ir_config.ensure_runtime_dirs()
    judgments_path = _ir_config.paths.state_dir / "manual_judgments.json"
    save_json_atomic(judgments_path, data)


def _compute_ir_manual_metrics(judgments: list) -> dict:
    if not judgments:
        return {}
    queries: dict = {}
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
    return {
        "query_count": len(queries),
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


# ── IE ────────────────────────────────────────────────────
from skills_ie.config import load_config as ie_load_config
from skills_ie.evaluation import evaluate_extraction, load_manual_judgments as ie_load_manual, save_manual_judgment as ie_save_judgment
from skills_ie.extractor import EXTRACTED_FIELDS, SkillsIESystem
from skills_ie.remote_llm import call_openai_compatible_json
from skills_ie.web import (
    DEFAULT_VARIANT, SUPPORTED_VARIANTS, VARIANT_DESCRIPTIONS, VARIANT_LABELS,
    _copy_extraction_values, _copy_full_extraction,
)

_ie_config = ie_load_config(_PROJECT_ROOT / "ie_system" / "configs" / "ie_config.json")

_ie_variant_cache: dict = {}
_ie_api_summary_cache: dict = {}
_ie_api_summary_lock = Lock()
_ie_bootstrap = SkillsIESystem(_ie_config, variant=DEFAULT_VARIANT)
_ie_bootstrap.load_data()
_ie_bootstrap.extract_all()


def _is_ie_variant_enabled(variant: str) -> bool:
    return variant != "api" or _ie_config.remote_llm.enabled


def _normalize_ie_variant(variant: str | None) -> str:
    normalized = (variant or "").strip() or DEFAULT_VARIANT
    if normalized not in SUPPORTED_VARIANTS:
        raise ValueError(f"unsupported variant: {normalized}")
    if not _is_ie_variant_enabled(normalized):
        raise RuntimeError(f"variant unavailable: {normalized}")
    return normalized


def _get_ie_variant_bundle(variant: str) -> dict:
    variant = _normalize_ie_variant(variant)
    if variant in _ie_variant_cache:
        return _ie_variant_cache[variant]
    ie = SkillsIESystem(_ie_config, variant=variant)
    ie.load_data()
    ie.extract_all()
    gt_path = _ie_config.resolve_eval_path(None)
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
    _ie_variant_cache[variant] = bundle
    return bundle


def _normalize_ie_summary_payload(payload: dict) -> dict:
    summary = str(payload.get("summary", "")).strip()
    highlights_raw = payload.get("highlights", [])
    highlights: list[str] = []
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


def _build_ie_api_summary_prompt(detail: dict) -> str:
    extraction_json = json.dumps(
        _copy_extraction_values(detail.get("extraction", {})),
        ensure_ascii=False,
        indent=2,
    )
    source_text = str(detail.get("source_text", "")).strip()[:7000]
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
        "- The summary should be 2-4 Chinese sentences describing likely usage flow and capabilities.\n"
        "- Do not invent outcomes, saved files, evaluated scores, or concrete execution results.\n"
        "- Highlights should be short Chinese fragments, each under 18 characters.\n"
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


def _get_ie_api_summary(bundle: dict, skill_id: str) -> dict:
    cache_key = (bundle["variant"], skill_id)
    with _ie_api_summary_lock:
        cached = _ie_api_summary_cache.get(cache_key)
    if cached is not None:
        return cached

    if not _ie_config.remote_llm.enabled:
        payload = {
            "available": False,
            "summary": "",
            "highlights": [],
            "error": "remote_llm disabled in config",
            "model": _ie_config.remote_llm.model,
        }
        with _ie_api_summary_lock:
            _ie_api_summary_cache.setdefault(cache_key, payload)
            return _ie_api_summary_cache[cache_key]

    event = bundle["events_by_skill_id"].get(skill_id)
    if not event:
        raise KeyError(skill_id)

    doc = bundle["docs_by_skill_id"].get(skill_id, {})
    source_text = bundle["ie"].get_document_source_text(doc) if doc else ""
    detail = {
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
        "source_text": source_text,
        "extraction": _copy_full_extraction(event.get("extraction", {})),
    }
    summary_config = replace(
        _ie_config.remote_llm,
        system_prompt="You are a skill capability summarization engine. Return strict JSON only.",
        temperature=0.0,
        max_output_tokens=min(_ie_config.remote_llm.max_output_tokens, 600),
    )
    prompt = _build_ie_api_summary_prompt(detail)
    try:
        raw_payload = call_openai_compatible_json(summary_config, prompt)
        normalized = _normalize_ie_summary_payload(raw_payload)
        normalized["model"] = summary_config.model
        if not normalized["available"]:
            normalized["error"] = "empty summary payload"
    except Exception as exc:
        normalized = {
            "available": False,
            "summary": "",
            "highlights": [],
            "error": str(exc),
            "model": summary_config.model,
        }

    with _ie_api_summary_lock:
        _ie_api_summary_cache.setdefault(cache_key, normalized)
        return _ie_api_summary_cache[cache_key]


# ── Multimedia ────────────────────────────────────────────
from ir_engine import MultimediaIR
from ie_engine import MultimediaIE, generate_report

_mm_data_dir = _PROJECT_ROOT / "multimedia_system" / "data"
_mm_videos_file = _mm_data_dir / "bilibili_videos.json"
_mm_extractions_file = _mm_data_dir / "extraction_results.json"

_mm_videos = json.loads(_mm_videos_file.read_text(encoding="utf-8"))
_mm_extractions = json.loads(_mm_extractions_file.read_text(encoding="utf-8")) if _mm_extractions_file.exists() else []
_mm_ext_map = {e["bvid"]: e for e in _mm_extractions}

_mm_ir = MultimediaIR()
_mm_ir.build_index(_mm_videos)

_mm_ie = MultimediaIE()
_mm_ie.load_data(_mm_videos_file)
_mm_report = generate_report(_mm_extractions, _mm_videos) if _mm_extractions else {}

# ═══════════════════════════════════════════════════════════
#  Flask 应用
# ═══════════════════════════════════════════════════════════

app = Flask(__name__, template_folder="templates")


@app.get("/")
def index():
    """统一入口页面。"""
    return render_template("unified.html")


# ═══════════════════════════════════════════════════════════
#  IR API
# ═══════════════════════════════════════════════════════════

@app.get("/api/ir/search")
def api_ir_search():
    query = request.args.get("q", "").strip()
    top_k_str = request.args.get("top_k", "10").strip()
    mode = request.args.get("mode", "hybrid").strip()
    if mode == "text":
        mode = "tfidf"
    if mode not in {"hybrid", "tfidf", "bm25"}:
        mode = "hybrid"
    try:
        top_k = max(1, min(int(top_k_str), 20))
    except ValueError:
        top_k = 10
    results = _ir_engine.search(query, top_k=top_k, mode=mode) if query else []
    eval_matches = _load_ir_eval_matches(query, top_k) if query else []
    query_review = review_query_results(query, results, eval_matches) if query else {"status": "idle", "findings": []}
    return jsonify({
        "query": query, "top_k": top_k, "mode": mode,
        "result_count": len(results), "results": results,
        "eval_matches": eval_matches,
        "query_review": query_review,
    })


@app.get("/api/ir/metrics")
def api_ir_metrics():
    runtime_review = review_runtime_snapshot(_ir_config)
    live_benchmarks = build_live_benchmark_review(
        _ir_config, _ir_engine,
        eval_names=[_ir_config.default_eval_set, "multilingual.json"],
        top_k=_ir_config.default_top_k,
    )
    manual_data = _load_ir_manual_judgments()
    manual_metrics = _compute_ir_manual_metrics(manual_data.get("judgments", []))
    return jsonify({
        "index_stats": {
            "document_count": len(_ir_engine.documents),
            "index_terms": len(_ir_engine.idf),
            "bm25_terms": len(_ir_engine.bm25_idf),
        },
        "metrics": runtime_review.get("metrics_report", {}),
        "failure_buckets": runtime_review.get("failure_buckets", {}).get("failure_buckets", {}),
        "findings": runtime_review.get("findings", []),
        "live_benchmarks": live_benchmarks,
        "manual_metrics": manual_metrics,
    })


@app.post("/api/ir/judge")
def api_ir_judge():
    body = request.get_json(silent=True) or {}
    query = body.get("query", "").strip()
    skill_name = body.get("skill_name", "").strip()
    label = body.get("label", "").strip()
    rank = body.get("rank", 0)
    if not query or not skill_name or label not in ("relevant", "partial", "not_relevant"):
        return jsonify({"ok": False, "error": "invalid input"}), 400
    manual_data = _load_ir_manual_judgments()
    judgments = manual_data.get("judgments", [])
    judgments = [j for j in judgments if not (j["query"] == query and j["skill_name"] == skill_name)]
    judgments.append({
        "query": query, "skill_name": skill_name, "label": label,
        "rank": rank, "timestamp": utc_now_iso(),
    })
    manual_data["judgments"] = judgments
    manual_data["summary"] = _compute_ir_manual_metrics(judgments)
    _save_ir_manual_judgments(manual_data)
    return jsonify({"ok": True, "total_judgments": len(judgments)})


@app.get("/api/ir/healthz")
def api_ir_healthz():
    return jsonify({
        "ok": True,
        "document_count": len(_ir_engine.documents),
        "index_terms": len(_ir_engine.idf),
        "bm25_terms": len(_ir_engine.bm25_idf),
    })

# ═══════════════════════════════════════════════════════════
#  IE API
# ═══════════════════════════════════════════════════════════

@app.get("/api/ie/variants")
def api_ie_variants():
    return jsonify([
        {"id": v, "label": VARIANT_LABELS[v], "description": VARIANT_DESCRIPTIONS[v],
         "enabled": _is_ie_variant_enabled(v)}
        for v in SUPPORTED_VARIANTS
    ])


@app.get("/api/ie/workbench")
def api_ie_workbench():
    try:
        variant = _normalize_ie_variant(request.args.get("variant"))
    except (ValueError, RuntimeError):
        variant = DEFAULT_VARIANT
    bundle = _get_ie_variant_bundle(variant)
    ie = bundle["ie"]
    manual_data = ie_load_manual(_ie_config)
    return jsonify({
        "summary": {
            "variant": variant,
            "variant_label": VARIANT_LABELS[variant],
            "total_docs": len(ie.documents),
            "total_extractions": len(ie.extraction_results),
            "api_description_enabled": bool(_ie_config.remote_llm.enabled),
        },
        "available_variants": [
            {"id": v, "label": VARIANT_LABELS[v], "description": VARIANT_DESCRIPTIONS[v],
             "enabled": _is_ie_variant_enabled(v)}
            for v in SUPPORTED_VARIANTS
        ],
        "events": [{
            "skill_id": e.get("skill_id", ""),
            "skill_name": e.get("skill_name", ""),
            "owner": e.get("owner", ""),
            "category": e.get("category", ""),
            "detail_url": e.get("detail_url", ""),
            "description_preview": e.get("description_preview", ""),
            "variant": e.get("variant", ""),
            "event_summary": e.get("event_summary", ""),
            "info_point_count": e.get("info_point_count", 0),
            "evidence_count": e.get("evidence_count", 0),
            "extraction": _copy_extraction_values(e.get("extraction", {})),
        } for e in ie.extraction_results],
        "report": bundle["report"],
        "manual_metrics": manual_data.get("summary", {}),
        "auto_eval": bundle["auto_eval"],
    })


@app.get("/api/ie/events/<skill_id>")
def api_ie_event_detail(skill_id: str):
    try:
        bundle = _get_ie_variant_bundle(request.args.get("variant"))
    except (ValueError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    event = bundle["events_by_skill_id"].get(skill_id)
    if not event:
        return jsonify({"ok": False, "error": "skill not found"}), 404
    doc = bundle["docs_by_skill_id"].get(skill_id, {})
    source_text = bundle["ie"].get_document_source_text(doc) if doc else ""
    detail = {
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
        "source_text": source_text,
        "extraction": _copy_full_extraction(event.get("extraction", {})),
    }
    return jsonify({"ok": True, "event": detail})


@app.get("/api/ie/describe/<skill_id>")
def api_ie_describe(skill_id: str):
    try:
        bundle = _get_ie_variant_bundle(request.args.get("variant"))
    except (ValueError, RuntimeError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    if skill_id not in bundle["events_by_skill_id"]:
        return jsonify({"ok": False, "error": "skill not found"}), 404
    return jsonify({"ok": True, "description": _get_ie_api_summary(bundle, skill_id)})


@app.get("/api/ie/search")
def api_ie_search():
    query = request.args.get("q", "").strip()
    field = request.args.get("field", "").strip() or None
    top_k_str = request.args.get("top_k", "10").strip()
    try:
        top_k = max(1, min(int(top_k_str), 50))
    except ValueError:
        top_k = 10
    try:
        variant = _normalize_ie_variant(request.args.get("variant"))
        bundle = _get_ie_variant_bundle(variant)
    except (ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400
    results = bundle["ie"].search_extractions(query, field=field, top_k=top_k) if query else []
    return jsonify({
        "query": query, "field": field, "variant": variant,
        "top_k": top_k, "result_count": len(results), "results": results,
    })


@app.post("/api/ie/judge")
def api_ie_judge():
    body = request.get_json(silent=True) or {}
    skill_name = body.get("skill_name", "").strip()
    field = body.get("field", "").strip()
    label = body.get("label", "").strip()
    value = body.get("value", "").strip()
    variant = body.get("variant", "").strip()
    if not skill_name or not field or label not in ("correct", "incorrect", "partial"):
        return jsonify({"ok": False, "error": "invalid input"}), 400
    summary = ie_save_judgment(_ie_config, skill_name=skill_name, field=field,
                               label=label, value=value, variant=variant)
    return jsonify({"ok": True, "summary": summary})


@app.get("/api/ie/report")
def api_ie_report():
    try:
        bundle = _get_ie_variant_bundle(request.args.get("variant"))
    except (ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(bundle["report"])


@app.get("/api/ie/extract")
def api_ie_extract():
    text = request.args.get("text", "").strip()
    if not text:
        return jsonify({"error": "missing text parameter"}), 400
    try:
        variant = _normalize_ie_variant(request.args.get("variant"))
        bundle = _get_ie_variant_bundle(variant)
    except (ValueError, RuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(bundle["ie"].extract_debug_payload(text, variant=variant))


@app.get("/api/ie/healthz")
def api_ie_healthz():
    return jsonify({
        "ok": True,
        "document_count": len(_ie_bootstrap.documents),
        "default_variant": DEFAULT_VARIANT,
    })


# ═══════════════════════════════════════════════════════════
#  Multimedia API
# ═══════════════════════════════════════════════════════════

@app.get("/api/mm/healthz")
def api_mm_healthz():
    return jsonify({"ok": True, "videos": len(_mm_videos), "extractions": len(_mm_extractions)})


@app.get("/api/mm/videos")
def api_mm_videos():
    cat = request.args.get("category", "").strip()
    filtered = [v for v in _mm_videos if v.get("category") == cat] if cat else _mm_videos
    return jsonify({"count": len(filtered), "videos": filtered})


@app.get("/api/mm/video/<bvid>")
def api_mm_video_detail(bvid: str):
    video = next((v for v in _mm_videos if v["bvid"] == bvid), None)
    if not video:
        return jsonify({"error": "not found"}), 404
    return jsonify({"video": video, "extraction": _mm_ext_map.get(bvid, {})})


@app.get("/api/mm/search")
def api_mm_search():
    query = request.args.get("q", "").strip()
    mode = request.args.get("mode", "hybrid").strip()
    try:
        top_k = max(1, min(int(request.args.get("top_k", "10")), 50))
    except ValueError:
        top_k = 10
    try:
        min_score = float(request.args.get("min_score", "0.0"))
    except ValueError:
        min_score = 0.0
    if not query:
        return jsonify({"results": [], "query": "", "mode": mode})
    if mode == "image":
        tw, bw, iw = 0.0, 0.0, 1.0
    elif mode == "text":
        tw, bw, iw = 0.5, 0.5, 0.0
    else:
        tw, bw, iw = 0.35, 0.35, 0.30
    results = _mm_ir.search(query, top_k=top_k, tfidf_weight=tw, bm25_weight=bw,
                            image_weight=iw, min_score=min_score)
    return jsonify({"results": results, "query": query, "mode": mode})


@app.get("/api/mm/extract/<bvid>")
def api_mm_extract_one(bvid: str):
    video = next((v for v in _mm_videos if v["bvid"] == bvid), None)
    if not video:
        return jsonify({"error": "not found"}), 404
    extraction = _mm_ie.extract_one(video)
    return jsonify(extraction)


@app.get("/api/mm/report")
def api_mm_report():
    return jsonify(_mm_report)


@app.get("/api/mm/categories")
def api_mm_categories():
    from collections import Counter
    cats = Counter(v.get("category", "未知") for v in _mm_videos)
    return jsonify([{"name": k, "count": v} for k, v in cats.most_common()])


@app.get("/api/mm/covers/<filename>")
def api_mm_serve_cover(filename: str):
    return send_from_directory(str(_mm_data_dir / "covers"), filename)


# ═══════════════════════════════════════════════════════════
#  启动入口
# ═══════════════════════════════════════════════════════════

def serve_web(host: str = "127.0.0.1", port: int = 5003, debug: bool = False):
    print(f"\n  🚀 统一检索与抽取系统")
    print(f"     地址: http://{host}:{port}")
    print(f"     IR 文档: {len(_ir_engine.documents)} | IE 文档: {len(_ie_bootstrap.documents)} | MM 视频: {len(_mm_videos)}")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="统一检索与抽取 Web 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5003)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    serve_web(host=args.host, port=args.port, debug=args.debug)
