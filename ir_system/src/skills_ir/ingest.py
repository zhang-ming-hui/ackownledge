"""IR 子系统的数据采集协调层。

这里不实现爬虫本身，而是把 `paqu.py` 暴露的采集能力
整理成更适合 IR 子系统调用的接口。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict

from .config import IRConfig


def dataset_stats(path: Path) -> Dict:
    """读取数据文件的存在性、记录数和更新时间。"""
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


def is_stale(path: Path, stale_after_hours: int) -> bool:
    """判断数据文件是否已经超过允许的新鲜度窗口。"""
    if not path.exists():
        return True
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return datetime.now(timezone.utc) - modified_at > timedelta(hours=stale_after_hours)


def run_ingest(
    config: IRConfig,
    target_count: int | None = None,
    sleep_seconds: float | None = None,
    headless: bool = True,
) -> Dict:
    """触发一次共享数据集采集，并返回采集前后的数据快照。"""
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
