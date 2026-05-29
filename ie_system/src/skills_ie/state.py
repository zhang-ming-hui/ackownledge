"""
IE 子系统的状态持久化与时间工具。

提供整个 IE 子系统的通用基础设施：
  1. utc_now_iso()          — 生成 UTC ISO 时间戳（去微秒），用于报告和状态记录
  2. save_json_atomic()     — 原子写入 JSON，避免写一半时被读者读到脏数据
  3. load_json()            — 安全读取 JSON，文件不存在时返回默认值

原子写入策略：
  先写到同目录的临时文件，完成后用 os.replace() 原子替换目标路径。
  这确保并发读取者永远看不到不完整的 JSON 内容。

注意：
  这里的是 IE 子系统内部的 state 模块，与 ir_system 的 state 独立。
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def utc_now_iso() -> str:
    """
    返回去掉微秒的 UTC ISO 时间戳。
    
    格式示例: "2026-05-29T14:30:00+00:00"
    微秒信息对报告/日志无意义，显式丢弃以减少噪声。
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def save_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    """
    以原子方式写入 JSON 文件。
    
    实现：
      1. 确保父目录存在
      2. 在同目录创建一个 .tmp 临时文件
      3. 写入完整 JSON（ensure_ascii=False 保留中文，indent=2 可读性）
      4. 用 os.replace() 原子替换原文件
    
    这个策略保证目标文件 \要么存在且完整，要么不存在\，
    不会出现"正在写"的中间状态。读取方不需要加锁。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f"{path.stem}.",        # 与目标同名，方便调试时辨认
        suffix=f".tmp{path.suffix}",
        delete=False,                   # 手动控制替换时机
    ) as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        temp_path = Path(file.name)
    temp_path.replace(path)


def load_json(path: Path, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    安全读取 JSON 文件。
    
    若文件不存在，返回 default（如果指定）或空 dict。
    这与 save_json_atomic 配对使用：新建项目时不会有文件，自动回退到默认值。
    """
    if not path.exists():
        return {} if default is None else default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)
