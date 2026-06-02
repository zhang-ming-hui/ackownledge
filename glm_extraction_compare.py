from __future__ import annotations

import argparse
import json
import os
import sys
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from zhipuai import ZhipuAI

import glm_skill_story_test as glm_story


ROOT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT_DIR / "ie_system" / "runtime" / "glm_story_tests"
IE_SRC_DIR = ROOT_DIR / "ie_system" / "src"

if str(IE_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(IE_SRC_DIR))

from skills_ie import SkillsIESystem, load_config
import skills_ie.extractor as extractor_module


DEFAULT_MODEL = "glm-4.5-flash"


def make_safe_prompt_template(template: str) -> str:
    safe = template.replace("{", "{{").replace("}", "}}")
    safe = safe.replace("{{text}}", "{text}")
    safe = safe.replace("{{schema_hints}}", "{schema_hints}")
    return safe


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare baseline/enhanced/project-api/standalone-GLM extraction on one skill."
    )
    parser.add_argument("--skill-id", default=None, help="Exact skill id")
    parser.add_argument("--skill-name", default=glm_story.DEFAULT_SKILL_NAME, help="Skill name")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="GLM model name")
    parser.add_argument(
        "--max-chars",
        type=int,
        default=glm_story.DEFAULT_MAX_CHARS,
        help="Maximum number of source characters sent to each method",
    )
    return parser.parse_args()


def build_shared_input(skill_id: str | None, skill_name: str | None, max_chars: int) -> dict[str, Any]:
    documents = glm_story.load_dataset()
    document = glm_story.find_skill(documents, skill_id=skill_id, skill_name=skill_name)
    raw_text = glm_story.read_skill_text(document)
    focused_text = glm_story.build_focus_text(document, raw_text)
    shared_text = glm_story.trim_skill_text(focused_text, max_chars=max_chars)
    return {
        "document": document,
        "raw_text": raw_text,
        "focused_text": focused_text,
        "shared_text": shared_text,
    }


def call_glm_json(
    model: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    top_p: float,
) -> dict[str, Any]:
    api_key = os.getenv("ZHIPUAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing ZHIPUAI_API_KEY environment variable.")

    client = ZhipuAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        top_p=top_p,
    )
    content = response.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("GLM response content is empty.")
    try:
        payload = json.loads(glm_story.extract_json_text(content))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GLM returned non-JSON content: {content[:400]}") from exc
    return {
        "payload": payload,
        "usage": {
            "prompt_tokens": getattr(getattr(response, "usage", None), "prompt_tokens", None),
            "completion_tokens": getattr(getattr(response, "usage", None), "completion_tokens", None),
            "total_tokens": getattr(getattr(response, "usage", None), "total_tokens", None),
        },
        "raw_text": content,
    }


@contextmanager
def patched_project_api_glm(model: str) -> Any:
    original = extractor_module.call_openai_compatible_json

    def _patched_call(config: Any, prompt: str) -> dict[str, Any]:
        response = call_glm_json(
            model=model,
            system_prompt=config.system_prompt,
            user_prompt=prompt,
            temperature=float(getattr(config, "temperature", 0.0)),
            top_p=0.3,
        )
        return response["payload"]

    extractor_module.call_openai_compatible_json = _patched_call
    try:
        yield
    finally:
        extractor_module.call_openai_compatible_json = original


def run_project_method(text: str, variant: str, model: str) -> dict[str, Any]:
    config = load_config()
    if variant != "api":
        system = SkillsIESystem(config, variant=variant)
        payload = system.extract_debug_payload(text, variant=variant)
        return {
            "status": "ok",
            "variant": variant,
            "summary": payload.get("summary", {}),
            "evidence_count": payload.get("evidence_count", 0),
            "extraction": payload.get("extraction", {}),
        }

    remote_cfg = replace(
        config.remote_llm,
        enabled=True,
        api_key_env="ZHIPUAI_API_KEY",
        model=model,
        temperature=0.0,
        max_output_tokens=1600,
        prompt_template=make_safe_prompt_template(config.remote_llm.prompt_template),
    )
    api_config = replace(config, remote_llm=remote_cfg)
    system = SkillsIESystem(api_config, variant="api")
    with patched_project_api_glm(model=model):
        payload = system.extract_debug_payload(text, variant="api")
    api_debug = payload.get("gliner", {}) or {}
    model_error = api_debug.get("model_error")
    if model_error:
        raise RuntimeError(model_error)
    return {
        "status": "ok",
        "variant": "api",
        "summary": payload.get("summary", {}),
        "evidence_count": payload.get("evidence_count", 0),
        "extraction": payload.get("extraction", {}),
        "api_debug": api_debug,
    }


def standalone_to_project_shape(document: dict[str, Any], normalized: dict[str, Any]) -> dict[str, Any]:
    extraction = dict(normalized.get("structured_extraction", {}))
    extraction["evidence"] = normalized.get("evidence", {})
    return {
        "status": "ok",
        "variant": "standalone_glm",
        "summary": {
            "nonempty_fields": [
                field
                for field in ["platforms", "languages", "action_types", "target_domains", "output_formats", "metrics"]
                if extraction.get(field)
            ],
            "info_point_count": sum(
                1
                for field in ["platforms", "languages", "action_types", "target_domains", "output_formats", "metrics"]
                if extraction.get(field)
            ),
        },
        "evidence_count": sum(len(items or []) for items in extraction.get("evidence", {}).values()),
        "extraction": extraction,
        "story_title": normalized.get("story_title", ""),
        "story": normalized.get("story", ""),
        "summary_text": normalized.get("summary", ""),
    }


def run_standalone_glm(document: dict[str, Any], shared_text: str, model: str) -> dict[str, Any]:
    prompt = glm_story.build_prompt(document, shared_text)
    response = call_glm_json(
        model=model,
        system_prompt=(
            "You extract grounded information from skill documents. "
            "Return JSON only. Stay faithful to the source. "
            "Do not invent completed outcomes from conditional rules."
        ),
        user_prompt=prompt,
        temperature=0.0,
        top_p=0.3,
    )
    normalized = glm_story.normalize_result(response["payload"], document)
    shaped = standalone_to_project_shape(document, normalized)
    shaped["usage"] = response["usage"]
    shaped["raw_response"] = response["raw_text"]
    return shaped


def build_method_block(label: str, result: dict[str, Any]) -> str:
    if result.get("status") != "ok":
        return f"## {label}\n\nStatus: ERROR\n\n{result.get('error', '')}\n"

    extraction = result.get("extraction", {})
    lines = [
        f"## {label}",
        "",
        f"- nonempty_fields: {', '.join(result.get('summary', {}).get('nonempty_fields', [])) or '(none)'}",
        f"- info_point_count: {result.get('summary', {}).get('info_point_count', 0)}",
        f"- evidence_count: {result.get('evidence_count', 0)}",
        f"- platforms: {json.dumps(extraction.get('platforms', []), ensure_ascii=False)}",
        f"- languages: {json.dumps(extraction.get('languages', []), ensure_ascii=False)}",
        f"- action_types: {json.dumps(extraction.get('action_types', []), ensure_ascii=False)}",
        f"- target_domains: {json.dumps(extraction.get('target_domains', []), ensure_ascii=False)}",
        f"- output_formats: {json.dumps(extraction.get('output_formats', []), ensure_ascii=False)}",
        f"- metrics: {json.dumps(extraction.get('metrics', []), ensure_ascii=False)}",
    ]
    if result.get("summary_text"):
        lines.extend(["", f"summary_text: {result['summary_text']}"])
    if result.get("story"):
        lines.extend(["", f"story_title: {result.get('story_title', '')}", "", result["story"]])
    return "\n".join(lines) + "\n"


def render_markdown(report: dict[str, Any]) -> str:
    parts = [
        f"# GLM Extraction Comparison: {report['skill_name']}",
        "",
        f"- skill_id: {report['skill_id']}",
        f"- model: {report['model']}",
        f"- shared_text_length: {report['shared_input']['shared_text_length']}",
        "",
        "## Shared Input Preview",
        "",
        "```text",
        report["shared_input"]["text_preview"],
        "```",
        "",
    ]
    for label in ["baseline", "enhanced", "project_api_glm", "standalone_glm"]:
        parts.append(build_method_block(label, report["methods"][label]))
    return "\n".join(parts).strip() + "\n"


def safe_run(method_name: str, fn: Any) -> dict[str, Any]:
    try:
        return fn()
    except Exception as exc:
        return {"status": "error", "error": f"{method_name}: {exc}"}


def main() -> int:
    args = parse_args()
    shared = build_shared_input(args.skill_id, args.skill_name, args.max_chars)
    document = shared["document"]
    skill_name = str(document.get("skill_name", "skill")).strip().lower()
    safe_name = glm_story.re.sub(r"[^a-z0-9._-]+", "-", skill_name).strip("-") or "skill"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = OUTPUT_DIR / f"{safe_name}.comparison.json"
    markdown_path = OUTPUT_DIR / f"{safe_name}.comparison.md"

    methods = {
        "baseline": safe_run("baseline", lambda: run_project_method(shared["shared_text"], "baseline", args.model)),
        "enhanced": safe_run("enhanced", lambda: run_project_method(shared["shared_text"], "enhanced", args.model)),
        "project_api_glm": safe_run("project_api_glm", lambda: run_project_method(shared["shared_text"], "api", args.model)),
        "standalone_glm": safe_run("standalone_glm", lambda: run_standalone_glm(document, shared["shared_text"], args.model)),
    }

    report = {
        "skill_id": str(document.get("skill_id", "")).strip(),
        "skill_name": str(document.get("skill_name", "")).strip(),
        "detail_url": str(document.get("detail_url", "")).strip(),
        "model": args.model,
        "shared_input": {
            "raw_text_length": len(shared["raw_text"]),
            "focused_text_length": len(shared["focused_text"]),
            "shared_text_length": len(shared["shared_text"]),
            "text_preview": shared["shared_text"][:1600],
        },
        "methods": methods,
    }

    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nSaved JSON: {report_path}")
    print(f"Saved Markdown: {markdown_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
