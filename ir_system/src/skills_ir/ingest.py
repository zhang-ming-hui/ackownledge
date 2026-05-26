from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict

from .config import IRConfig

# 获取数据集文件的统计信息
def dataset_stats(path: Path) -> Dict:
    if not path.exists():
        return {
            "exists": False,
            "path": str(path),
            "record_count": 0,
            "last_modified": None,
        }

    import json

    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    return {
        "exists": True,
        "path": str(path),
        "record_count": len(payload),
        "last_modified": datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).replace(microsecond=0).isoformat(),
    }

# 检查数据文件是否已过期
# 如果文件不存在 → 返回 True（视为过期）

# 如果文件的最后修改时间超过了 stale_after_hours 小时 → 返回 True

# 否则返回 False
def is_stale(path: Path, stale_after_hours: int) -> bool:
    if not path.exists():
        return True
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return datetime.now(timezone.utc) - modified_at > timedelta(hours=stale_after_hours)

# 执行数据采集流程
# config: 配置对象，包含采集目标和路径设置
# target_count: 要采集的目标数量（默认从配置读取）
# sleep_seconds: 请求间隔秒数（默认从配置读取）
# headless: 是否无头模式运行浏览器（默认 True）
def run_ingest(
    config: IRConfig,
    target_count: int | None = None,
    sleep_seconds: float | None = None,
    headless: bool = True,
) -> Dict:
    from paqu import crawl_skills

    target_count = target_count or config.ingest_target_count
    sleep_seconds = sleep_seconds if sleep_seconds is not None else config.ingest_sleep_seconds
    before = dataset_stats(config.paths.data_file)
    crawl_skills(
        target_count=target_count,
        sleep_seconds=sleep_seconds,
        headless=headless,
    )
    after = dataset_stats(config.paths.data_file)
    return {
        "target_count": target_count,
        "sleep_seconds": sleep_seconds,
        "headless": headless,
        "before": before,
        "after": after,
    }
