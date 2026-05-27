"""IR 数据健康检查。

该模块从共享数据集里提取结构质量信号，用于发现：
- 关键字段缺失
- 数值字段脏数据
- repo URL 规范化问题
- skill_name 重复问题
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Dict
from urllib.parse import urlparse

from .config import IRConfig
from .state import save_json_atomic, utc_now_iso


IMPORTANT_FIELDS = [
    "skill_id",
    "skill_name",
    "owner",
    "repo",
    "description",
    "category",
    "detail_url",
    "repo_url",
    "weekly_installs_num",
    "github_stars_num",
]


def _repo_url_bucket(url: str) -> str:
    """把仓库链接按是否规范、是否缺失分桶统计。"""
    if not url:
        return "missing"
    parsed = urlparse(url)
    path = parsed.path.lower()
    if "/blob/" in path or "/tree/" in path:
        return "non_canonical_github_subpage"
    if "github.com" in parsed.netloc and len(path.strip("/").split("/")) >= 2:
        return "canonical_github_repo"
    return "other"


def build_data_health_report(config: IRConfig) -> Dict:
    """生成一份数据集健康报告，但不落盘。"""
    with config.paths.data_file.open("r", encoding="utf-8") as file:
        records = json.load(file)

    missing_field_counts = Counter()
    dirty_numeric_samples: dict[str, list[str]] = defaultdict(list)
    category_counts = Counter()
    owner_counts = Counter()
    repo_counts = Counter()
    repo_url_buckets = Counter()
    duplicate_skill_names = Counter()

    for record in records:
        for field in IMPORTANT_FIELDS:
            value = record.get(field)
            if value in (None, "", []):
                missing_field_counts[field] += 1

        category_counts[str(record.get("category") or "missing")] += 1
        owner_counts[str(record.get("owner") or "missing")] += 1
        repo_counts[str(record.get("repo") or "missing")] += 1
        duplicate_skill_names[str(record.get("skill_name") or "missing")] += 1
        repo_url_buckets[_repo_url_bucket(str(record.get("repo_url") or ""))] += 1

        weekly_installs = str(record.get("weekly_installs") or "")
        github_stars = str(record.get("github_stars") or "")
        if weekly_installs and record.get("weekly_installs_num") in (None, ""):
            dirty_numeric_samples["weekly_installs"].append(weekly_installs)
        if github_stars and record.get("github_stars_num") in (None, ""):
            dirty_numeric_samples["github_stars"].append(github_stars)

    duplicate_name_examples = [
        {"skill_name": name, "count": count}
        for name, count in duplicate_skill_names.most_common()
        if count > 1
    ][:20]

    report = {
        "generated_at": utc_now_iso(),
        "dataset_path": str(config.paths.data_file),
        "record_count": len(records),
        "important_field_missing_counts": dict(missing_field_counts),
        "important_field_missing_rates": {
            field: missing_field_counts[field] / len(records) if records else 0.0
            for field in IMPORTANT_FIELDS
        },
        "repo_url_buckets": dict(repo_url_buckets),
        "top_categories": category_counts.most_common(10),
        "top_owners": owner_counts.most_common(10),
        "top_repos": repo_counts.most_common(10),
        "duplicate_skill_name_examples": duplicate_name_examples,
        "dirty_numeric_samples": {
            key: values[:10] for key, values in dirty_numeric_samples.items()
        },
        "recommendations": [
            "优先清理 repo_url 的 canonical 化，减少 blob/tree 子页面链接。",
            "为 description/category/数值字段增加抓取后校验，避免静默脏值入库。",
            "对重复 skill_name 建立去重或来源分层规则，避免影响检索与评测。",
        ],
    }
    return report


def save_data_health_report(config: IRConfig) -> Dict:
    """生成并保存数据健康报告。"""
    report = build_data_health_report(config)
    save_json_atomic(config.paths.data_health_report_file, report)
    return report
