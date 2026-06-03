from __future__ import annotations

import json
import os
from typing import Any, Dict
from urllib import error, request

from .config import RemoteLLMConfig


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines:
            lines = lines[1:]
        while lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def _extract_first_json_object(text: str) -> str | None:
    start = -1
    depth = 0
    in_string = False
    escape = False
    for index, char in enumerate(text):
        if start < 0:
            if char == "{":
                start = index
                depth = 1
            continue
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _parse_json_like_content(content: str) -> Any:
    cleaned = _strip_code_fences(content)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        candidate = _extract_first_json_object(cleaned)
        if candidate:
            return json.loads(candidate)
        raise


def _should_try_next_model(status_code: int, detail: str) -> bool:
    if status_code in {404, 429, 503}:
        return True
    lowered = detail.lower()
    retryable_markers = (
        "temporarily rate-limited",
        "no healthy upstream",
        "no endpoints found",
        "provider returned error",
    )
    return any(marker in lowered for marker in retryable_markers)


def _extract_message_content(parsed: Dict[str, Any]) -> str:
    choices = parsed.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("remote LLM response missing choices")

    message = choices[0].get("message", {})
    content = message.get("content")
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
        content = "\n".join(part for part in text_parts if part).strip()
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("remote LLM response missing text content")
    return content


def call_openai_compatible_json(
    config: RemoteLLMConfig,
    prompt: str,
) -> Dict[str, Any]:
    api_key = os.getenv(config.api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"missing API key env: {config.api_key_env}")

    base_url = config.api_base.rstrip("/")
    url = f"{base_url}/chat/completions"
    model_candidates = [item.strip() for item in str(config.model).split(",") if item.strip()]
    if not model_candidates:
        raise RuntimeError("remote LLM config missing model")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    headers.update(config.extra_headers)
    attempted: list[str] = []
    last_error: Exception | None = None

    for index, model_name in enumerate(model_candidates):
        attempted.append(model_name)
        payload = {
            "model": model_name,
            "temperature": config.temperature,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": config.system_prompt},
                {"role": "user", "content": prompt},
            ],
        }
        if config.max_output_tokens > 0:
            payload["max_tokens"] = config.max_output_tokens

        body = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=body, headers=headers, method="POST")

        try:
            with request.urlopen(req, timeout=config.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
            parsed = json.loads(raw)
            content = _extract_message_content(parsed)
            result = _parse_json_like_content(content)
            if isinstance(result, dict):
                result.setdefault("_resolved_model", model_name)
            return result
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = RuntimeError(f"remote LLM HTTP {exc.code}: {detail}")
            if index < len(model_candidates) - 1 and _should_try_next_model(exc.code, detail):
                continue
            raise last_error from exc
        except error.URLError as exc:
            last_error = RuntimeError(f"remote LLM request failed: {exc}")
            if index < len(model_candidates) - 1:
                continue
            raise last_error from exc
        except (json.JSONDecodeError, RuntimeError) as exc:
            if isinstance(exc, json.JSONDecodeError):
                content = ""
                last_error = RuntimeError("remote LLM returned malformed JSON")
            else:
                last_error = exc
            if index < len(model_candidates) - 1:
                continue
            raise last_error

    attempted_text = ", ".join(attempted)
    if last_error is not None:
        raise RuntimeError(f"remote LLM fallback exhausted after models [{attempted_text}]: {last_error}")
    raise RuntimeError(f"remote LLM fallback exhausted after models [{attempted_text}]")
