'''这是一个数据质量监控工具，通过分析数据集中的各种指标，生成一份健康报告，帮助发现数据问题并指导后续优化。'''
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

# 对仓库URL进行分类（分桶）
def _repo_url_bucket(url: str) -> str:
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
        # 检查每个重要字段是否为空
        for field in IMPORTANT_FIELDS:
            value = record.get(field)
            # 三种"空"的情况
            if value in (None, "", []):
                missing_field_counts[field] += 1
        
        # 统计各字段的分布情况
        category_counts[str(record.get("category") or "missing")] += 1
        owner_counts[str(record.get("owner") or "missing")] += 1
        repo_counts[str(record.get("repo") or "missing")] += 1
        # 统计同名技能
        duplicate_skill_names[str(record.get("skill_name") or "missing")] += 1
        repo_url_buckets[_repo_url_bucket(str(record.get("repo_url") or ""))] += 1

        # 检测"有原始值但没有解析后数值"的情况
        weekly_installs = str(record.get("weekly_installs") or "")
        github_stars = str(record.get("github_stars") or "")
        if weekly_installs and record.get("weekly_installs_num") in (None, ""):
            dirty_numeric_samples["weekly_installs"].append(weekly_installs)
        if github_stars and record.get("github_stars_num") in (None, ""):
            dirty_numeric_samples["github_stars"].append(github_stars)

    # 找出重复超过1次的（最多20个样例）
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
    report = build_data_health_report(config)
    save_json_atomic(config.paths.data_health_report_file, report)
    return report
