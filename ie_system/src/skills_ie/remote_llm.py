from __future__ import annotations

import json
import os
from typing import Any, Dict
from urllib import error, request

from .config import RemoteLLMConfig


def call_openai_compatible_json(
    config: RemoteLLMConfig,
    prompt: str,
) -> Dict[str, Any]:
    api_key = os.getenv(config.api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"missing API key env: {config.api_key_env}")

    base_url = config.api_base.rstrip("/")
    url = f"{base_url}/chat/completions"
    payload = {
        "model": config.model,
        "temperature": config.temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": config.system_prompt},
            {"role": "user", "content": prompt},
        ],
    }
    if config.max_output_tokens > 0:
        payload["max_tokens"] = config.max_output_tokens

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    headers.update(config.extra_headers)
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers=headers, method="POST")

    try:
        with request.urlopen(req, timeout=config.timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"remote LLM HTTP {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"remote LLM request failed: {exc}") from exc

    parsed = json.loads(raw)
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

    try:
        return json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"remote LLM returned non-JSON content: {content[:400]}") from exc
