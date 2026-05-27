"""IE 子系统的状态持久化与时间工具。"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def utc_now_iso() -> str:
    """返回去掉微秒的 UTC ISO 时间戳。"""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def save_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    """以原子方式写入 JSON 文件。"""
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
    """读取 JSON 文件；文件不存在时返回默认值。"""
    if not path.exists():
        return {} if default is None else default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)
