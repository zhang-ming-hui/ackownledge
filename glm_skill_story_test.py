from __future__ import annotations

import argparse
import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from zhipuai import ZhipuAI


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
DATA_FILE = DATA_DIR / "skills_data.json"
OUTPUT_DIR = ROOT_DIR / "ie_system" / "runtime" / "glm_story_tests"
IE_SRC_DIR = ROOT_DIR / "ie_system" / "src"
DEFAULT_SKILL_NAME = "domain-authority-auditor"
DEFAULT_MODEL = "glm-4.5-flash"
DEFAULT_MAX_CHARS = 8000

COMMON_END_MARKERS = [
    "Instructions",
    "Step 1: Preparation",
    "Validation Checkpoints",
    "Reference Materials",
    "Tips for Success",
    "Example",
]

if str(IE_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(IE_SRC_DIR))

from skills_ie import SkillsIESystem, load_config


def load_dataset() -> list[dict[str, Any]]:
    with DATA_FILE.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, list):
        raise RuntimeError(f"Unexpected dataset shape in {DATA_FILE}")
    return [item for item in payload if isinstance(item, dict)]


def find_skill(
    documents: list[dict[str, Any]],
    skill_id: str | None,
    skill_name: str | None,
) -> dict[str, Any]:
    if skill_id:
        for doc in documents:
            if str(doc.get("skill_id", "")).strip().lower() == skill_id.strip().lower():
                return doc
        raise RuntimeError(f"Skill id not found: {skill_id}")

    target_name = (skill_name or DEFAULT_SKILL_NAME).strip().lower()
    for doc in documents:
        if str(doc.get("skill_name", "")).strip().lower() == target_name:
            return doc

    partial_matches = [
        doc for doc in documents if target_name in str(doc.get("skill_name", "")).strip().lower()
    ]
    if partial_matches:
        return partial_matches[0]
    raise RuntimeError(f"Skill name not found: {skill_name or DEFAULT_SKILL_NAME}")


def read_skill_text(document: dict[str, Any]) -> str:
    candidate_keys = [
        "skill_md_text_path",
        "skill_md_raw_text_path",
        "skill_md_html_path",
    ]
    for key in candidate_keys:
        relative_path = str(document.get(key, "")).strip()
        if not relative_path:
            continue
        full_path = DATA_DIR / relative_path
        if full_path.exists() and full_path.is_file():
            return full_path.read_text(encoding="utf-8", errors="replace").strip()

    description = str(document.get("description", "")).strip()
    if description:
        return description
    raise RuntimeError("No readable skill text found for the selected document.")


def _extract_section(text: str, heading: str, next_headings: list[str]) -> str:
    start = text.find(heading)
    if start < 0:
        return ""

    start += len(heading)
    end_candidates = [len(text)]
    for marker in next_headings:
        index = text.find(marker, start)
        if index >= 0:
            end_candidates.append(index)
    end = min(end_candidates)
    return text[start:end].strip()


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def build_focus_text(document: dict[str, Any], raw_skill_text: str) -> str:
    description = _normalize_whitespace(str(document.get("description", "")).strip())
    text = raw_skill_text.strip()

    overview_end = len(text)
    for marker in ["When This Must Trigger", "What This Skill Does", *COMMON_END_MARKERS]:
        index = text.find(marker)
        if index >= 0:
            overview_end = min(overview_end, index)
    overview = _normalize_whitespace(text[:overview_end])

    triggers = _normalize_whitespace(
        _extract_section(
            text,
            "When This Must Trigger",
            ["What This Skill Does", "Quick Start", "Skill Contract", *COMMON_END_MARKERS],
        )
    )
    capabilities = _normalize_whitespace(
        _extract_section(
            text,
            "What This Skill Does",
            ["Quick Start", "Skill Contract", "Data Sources", *COMMON_END_MARKERS],
        )
    )
    sections: list[str] = []
    if description:
        sections.append(f"Description: {description}")
    if overview:
        sections.append(f"Overview: {overview}")
    if triggers:
        sections.append(f"When This Must Trigger: {triggers}")
    if capabilities:
        sections.append(f"What This Skill Does: {capabilities}")

    focused = "\n\n".join(section for section in sections if section)
    if focused:
        return focused

    fallback_end = len(text)
    for marker in COMMON_END_MARKERS:
        index = text.find(marker)
        if index >= 0:
            fallback_end = min(fallback_end, index)
    fallback = _normalize_whitespace(text[:fallback_end])
    return fallback or description


def build_prompt(document: dict[str, Any], skill_text: str) -> str:
    skill_name = str(document.get("skill_name", "")).strip()

    return f"""You are testing a GLM-based extraction workflow for one skill document.

Read the skill document and return JSON only.

Goals:
1. Extract structured information with the project's schema.
2. Write a fluent Chinese capability narrative that naturally combines the extracted facts into one hypothetical usage scenario.

JSON schema:
{{
  "skill_name": "...",
  "summary": "...",
  "structured_extraction": {{
    "platforms": ["..."],
    "languages": ["..."],
    "action_types": ["..."],
    "target_domains": ["..."],
    "output_formats": ["..."],
    "metrics": [
      {{
        "value": "...",
        "unit": "...",
        "meaning": "..."
      }}
    ]
  }},
  "evidence": {{
    "platforms": [{{"value": "...", "quote": "..."}}],
    "languages": [{{"value": "...", "quote": "..."}}],
    "action_types": [{{"value": "...", "quote": "..."}}],
    "target_domains": [{{"value": "...", "quote": "..."}}],
    "output_formats": [{{"value": "...", "quote": "..."}}],
    "metrics": [{{"value": "...", "unit": "...", "quote": "..."}}]
  }},
  "story_title": "...",
  "story": "..."
}}

Rules:
- Return valid JSON only. Do not wrap it in Markdown.
- Use empty arrays when a field is absent.
- Keep extracted values concise and canonical.
- Every evidence quote must be a short verbatim span from the source text.
- The source text below is a focused excerpt. Ignore repository paths, storage locations, handoff schemas, artifact-gate rules, worked examples, and optional placeholder connectors unless they are central to the skill itself.
- The story must be in Chinese, coherent, and based only on the source text.
- The story must not be a bullet list or a direct field dump.
- The story must describe the skill's capabilities and likely usage flow, not a fabricated completed case.
- The story should read like a short usage vignette: include one hypothetical role, one goal, and the likely steps of using the skill.
- Use hypothetical phrasing such as "可以", "会", "适合", "用于". Do not invent a specific audited object, runtime result, score, failure, or saved file.
- Do not say a veto was triggered, a score was capped, or a report was saved unless the source text states that such an event has already happened.
- If a metric is important, weave it into the story naturally as a capability or rule, not as an observed outcome.

Field guidance:
- platforms: extract primary products, platforms, or integrations the skill directly operates on. Ignore optional placeholder connectors such as "SEO tool", "AI monitor", "knowledge graph", "brand monitor", and "link database" unless they are the main subject of the skill.
- languages: programming languages or technical stacks only.
- action_types: short canonical verbs such as audit, analyze, compare, score, detect, generate, prioritize.
- target_domains: business or application domains such as marketing, SEO, content, security. Do not treat example customer site types such as "Content Publisher", "E-commerce", or "SaaS" as target domains unless the skill is specifically built only for that sector.
- output_formats: only concrete file/data formats such as json, markdown, pdf, csv, html, api. If the text only mentions reports, summaries, plans, or verdicts without naming an actual file/data format, return an empty array.
- metrics: keep only stable capability-level numbers such as item counts, dimensions, supported sources, or scoring ranges. Ignore trigger thresholds, handoff conditions, or scenario-specific example numbers.

Context:
- skill_name: {skill_name}

Focused skill source:
{skill_text}
"""


def trim_skill_text(skill_text: str, max_chars: int) -> str:
    text = skill_text.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    trimmed = text[:max_chars].rstrip()
    return (
        f"{trimmed}\n\n"
        f"[Source text truncated to the first {max_chars} characters for this API test.]"
    )


def extract_json_text(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
        return stripped.strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1].strip()
    return stripped


@lru_cache(maxsize=1)
def get_vocab_normalizer() -> SkillsIESystem:
    config = load_config()
    return SkillsIESystem(config, variant="baseline")


def normalize_vocab_value(value: str, field: str) -> str:
    normalizer = get_vocab_normalizer()
    normalized, _ = normalizer._normalize_to_vocab(value, field)
    return normalized or ""


def ensure_list_of_strings(value: Any, field: str | None = None) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if field:
            text = normalize_vocab_value(text, field)
        if text and text not in result:
            result.append(text)
    return result


def ensure_metrics(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    metrics: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized = {
            "value": str(item.get("value", "")).strip(),
            "unit": str(item.get("unit", "")).strip(),
            "meaning": str(item.get("meaning", "")).strip(),
        }
        key = (normalized["value"], normalized["unit"], normalized["meaning"])
        if not normalized["value"] or key in seen:
            continue
        seen.add(key)
        metrics.append(normalized)
    return metrics


def ensure_evidence(value: Any, metrics_mode: bool = False) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    evidence_items: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized = {
            "value": str(item.get("value", "")).strip(),
            "quote": str(item.get("quote", "")).strip(),
        }
        if metrics_mode:
            normalized["unit"] = str(item.get("unit", "")).strip()
        if normalized["value"]:
            evidence_items.append(normalized)
    return evidence_items


def filter_enum_evidence(
    values: list[str],
    evidence_items: list[dict[str, str]],
    field: str,
) -> list[dict[str, str]]:
    allowed = set(values)
    filtered: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in evidence_items:
        value = str(item.get("value", "")).strip()
        if field:
            value = normalize_vocab_value(value, field)
        if not value or value not in allowed:
            continue
        quote = str(item.get("quote", "")).strip()
        lowered_quote = quote.lower()
        if field == "target_domains" and (
            lowered_quote.startswith("category:")
            or "content publisher" in lowered_quote
            or "e-commerce" in lowered_quote
            or "saas" in lowered_quote
        ):
            continue
        item["value"] = value
        signature = (value, quote)
        if signature in seen:
            continue
        seen.add(signature)
        filtered.append(item)
    return filtered


def filter_metrics(metrics: list[dict[str, str]], evidence_items: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    filtered_metrics: list[dict[str, str]] = []
    filtered_evidence: list[dict[str, str]] = []
    seen_metric_keys: set[tuple[str, str, str]] = set()

    for metric in metrics:
        value = str(metric.get("value", "")).strip()
        unit = str(metric.get("unit", "")).strip()
        meaning = str(metric.get("meaning", "")).strip()
        if not value:
            continue
        if value.endswith("%"):
            continue
        key = (value, unit, meaning)
        if key in seen_metric_keys:
            continue
        seen_metric_keys.add(key)
        filtered_metrics.append(metric)

    allowed_metric_keys = {(m["value"], m["unit"]) for m in filtered_metrics}
    for item in evidence_items:
        value = str(item.get("value", "")).strip()
        unit = str(item.get("unit", "")).strip()
        quote = str(item.get("quote", "")).strip()
        lowered_quote = quote.lower()
        if (value, unit) not in allowed_metric_keys:
            continue
        if lowered_quote.startswith("when ") or "above 15%" in lowered_quote:
            continue
        filtered_evidence.append(item)

    return filtered_metrics, filtered_evidence


def normalize_result(payload: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    structured = payload.get("structured_extraction", {})
    evidence = payload.get("evidence", {})
    if not isinstance(structured, dict):
        structured = {}
    if not isinstance(evidence, dict):
        evidence = {}

    platforms = ensure_list_of_strings(structured.get("platforms"), field="platforms")
    languages = ensure_list_of_strings(structured.get("languages"), field="languages")
    action_types = ensure_list_of_strings(structured.get("action_types"), field="action_types")
    target_domains = ensure_list_of_strings(structured.get("target_domains"), field="target_domains")
    output_formats = ensure_list_of_strings(structured.get("output_formats"), field="output_formats")
    metrics = ensure_metrics(structured.get("metrics"))

    platform_evidence = filter_enum_evidence(
        platforms,
        ensure_evidence(evidence.get("platforms")),
        field="platforms",
    )
    language_evidence = filter_enum_evidence(
        languages,
        ensure_evidence(evidence.get("languages")),
        field="languages",
    )
    action_evidence = filter_enum_evidence(
        action_types,
        ensure_evidence(evidence.get("action_types")),
        field="action_types",
    )
    domain_evidence = filter_enum_evidence(
        target_domains,
        ensure_evidence(evidence.get("target_domains")),
        field="target_domains",
    )
    output_evidence = filter_enum_evidence(
        output_formats,
        ensure_evidence(evidence.get("output_formats")),
        field="output_formats",
    )
    metrics, metric_evidence = filter_metrics(metrics, ensure_evidence(evidence.get("metrics"), metrics_mode=True))

    return {
        "skill_id": str(document.get("skill_id", "")).strip(),
        "skill_name": str(payload.get("skill_name") or document.get("skill_name", "")).strip(),
        "owner": str(document.get("owner", "")).strip(),
        "category": str(document.get("category", "")).strip(),
        "detail_url": str(document.get("detail_url", "")).strip(),
        "summary": str(payload.get("summary", "")).strip(),
        "structured_extraction": {
            "platforms": platforms,
            "languages": languages,
            "action_types": action_types,
            "target_domains": target_domains,
            "output_formats": output_formats,
            "metrics": metrics,
        },
        "evidence": {
            "platforms": platform_evidence,
            "languages": language_evidence,
            "action_types": action_evidence,
            "target_domains": domain_evidence,
            "output_formats": output_evidence,
            "metrics": metric_evidence,
        },
        "story_title": str(payload.get("story_title", "")).strip(),
        "story": str(payload.get("story", "")).strip(),
    }


def call_glm(prompt: str, model: str) -> tuple[str, Any]:
    api_key = os.getenv("ZHIPUAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing ZHIPUAI_API_KEY environment variable.")

    client = ZhipuAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You extract grounded information from skill documents. "
                    "Return JSON only. Stay faithful to the source. "
                    "Do not invent completed outcomes from conditional rules."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        top_p=0.3,
    )
    content = response.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("GLM response content is empty.")
    return content, response


def build_output_path(document: dict[str, Any], output_path: str | None) -> Path:
    if output_path:
        return Path(output_path).resolve()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    skill_name = str(document.get("skill_name", "skill")).strip().lower()
    safe_name = re.sub(r"[^a-z0-9._-]+", "-", skill_name).strip("-") or "skill"
    return OUTPUT_DIR / f"{safe_name}.glm_story.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test GLM extraction and story generation on one skill document."
    )
    parser.add_argument("--skill-id", default=None, help="Exact skill id from data/skills_data.json")
    parser.add_argument("--skill-name", default=DEFAULT_SKILL_NAME, help="Skill name to test")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="GLM model name")
    parser.add_argument("--output", default=None, help="Optional output file path")
    parser.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        help="Maximum number of source characters sent to the model; 0 disables truncation",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve the skill document and prompt without calling the API",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    documents = load_dataset()
    document = find_skill(documents, skill_id=args.skill_id, skill_name=args.skill_name)
    raw_skill_text = read_skill_text(document)
    focused_skill_text = build_focus_text(document, raw_skill_text)
    skill_text = trim_skill_text(focused_skill_text, max_chars=args.max_chars)
    prompt = build_prompt(document, skill_text)
    output_path = build_output_path(document, args.output)
    prompt_path = output_path.with_suffix(".prompt.txt")
    source_path = output_path.with_suffix(".source.txt")

    if args.dry_run:
        preview = {
            "skill_id": document.get("skill_id", ""),
            "skill_name": document.get("skill_name", ""),
            "owner": document.get("owner", ""),
            "category": document.get("category", ""),
            "detail_url": document.get("detail_url", ""),
            "raw_text_length": len(raw_skill_text),
            "focused_text_length": len(focused_skill_text),
            "text_preview": skill_text[:800],
            "prompt_preview": prompt[:1800],
            "output_path": str(output_path),
            "prompt_path": str(prompt_path),
            "source_path": str(source_path),
        }
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    raw_content, response = call_glm(prompt, model=args.model)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path = output_path.with_suffix(".raw.txt")
    prompt_path.write_text(prompt, encoding="utf-8")
    source_path.write_text(skill_text, encoding="utf-8")
    raw_path.write_text(raw_content, encoding="utf-8")

    try:
        parsed = json.loads(extract_json_text(raw_content))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"GLM output is not valid JSON. Raw response saved to {raw_path}") from exc

    normalized = normalize_result(parsed, document)
    final_payload = {
        "model": args.model,
        "skill_id": normalized["skill_id"],
        "skill_name": normalized["skill_name"],
        "detail_url": normalized["detail_url"],
        "usage": {
            "prompt_tokens": getattr(getattr(response, "usage", None), "prompt_tokens", None),
            "completion_tokens": getattr(getattr(response, "usage", None), "completion_tokens", None),
            "total_tokens": getattr(getattr(response, "usage", None), "total_tokens", None),
        },
        "artifacts": {
            "prompt_file": str(prompt_path),
            "source_file": str(source_path),
            "raw_response_file": str(raw_path),
        },
        "result": normalized,
    }
    output_path.write_text(json.dumps(final_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(final_payload, ensure_ascii=False, indent=2))
    print(f"\nSaved JSON: {output_path}")
    print(f"Saved prompt: {prompt_path}")
    print(f"Saved source: {source_path}")
    print(f"Saved raw response: {raw_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
