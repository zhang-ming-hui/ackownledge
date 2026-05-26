from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def save_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f"{path.stem}.",
        suffix=f".tmp{path.suffix}",
        delete=False,
    ) as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        temp_path = Path(file.name)
    temp_path.replace(path)


def load_json(path: Path, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    if not path.exists():
        return {} if default is None else default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)
