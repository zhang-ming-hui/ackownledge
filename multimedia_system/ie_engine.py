"""多媒体 IE 引擎 — 从 B站视频元数据中抽取结构化信息字段。"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import jieba


# ─── IE 抽取器 ────────────────────────────────────────────────

class MultimediaIE:
    """从 B站视频数据中抽取 6 个信息字段。

    字段定义：
      - platforms: 平台（固定 "bilibili"）
      - categories: 分类/分区
      - entities: 关键实体（人名、作品名、品牌等，从标题/描述中抽取）
      - action_types: 内容类型或动作（教程、评测、搞笑、翻唱等）
      - metrics: 数量指标（播放量、点赞、投币、弹幕、时长）
      - keywords: 主题关键词（jieba TF-IDF 提取）
    """

    # 关键词分类词典
    ACTION_PATTERNS = {
        "教程": ["教程", "教学", "学习", "入门", "攻略", "指南"],
        "评测": ["评测", "测评", "体验", "试驾", "开箱"],
        "搞笑": ["搞笑", "整活", "鬼畜", "抽象"],
        "翻唱": ["翻唱", "演唱", "合唱", "cover"],
        "游戏实况": ["实况", "通关", "解说", "试玩", "直播"],
        "科普": ["科普", "揭秘", "解析", "背后", "真相", "原理"],
        "盘点": ["盘点", "排行", "合集", "总结"],
        "Vlog": ["vlog", "日常", "记录", "出行"],
        "影视解说": ["解说", "剧情", "电影", "电视剧"],
        "赛事": ["比赛", "决赛", "冠军", "世界杯"],
        "动画": ["动画", "动漫", "mad", "手书"],
        "音乐": ["音乐", "歌曲", "mv", "演奏", "节奏"],
        "短剧": ["短剧", "短片", "微电影"],
    }

    ENTITY_PATTERNS = {
        "游戏": ["鸣潮", "原神", "王者荣耀", "英雄联盟", "赛博朋克", "我的世界",
                "崩坏", "碧蓝航线", "明日方舟", "绝区零", "星穹铁道",
                "apex", "valorant", "csgo", "dota", "lol"],
        "动漫": ["瑞克和莫蒂", "火影忍者", "海贼王", "进击的巨人", "鬼灭之刃",
                "spy", "eva", "fate", "jojo"],
        "品牌": ["华为", "小米", "苹果", "奥迪", "比亚迪", "特斯拉",
                "bilibili", "抖音", "小红书", "百度", "腾讯", "阿里"],
        "人物": ["周深", "曾沛慈", "毕导", "孔子", "张艺谋"],
    }

    def __init__(self):
        self.videos: List[Dict] = []
        self._all_keywords: Counter = Counter()

    def load_data(self, data_file: Path) -> List[Dict]:
        """加载视频数据。"""
        self.videos = json.loads(data_file.read_text(encoding="utf-8"))
        return self.videos

    def extract_one(self, video: Dict) -> Dict:
        """对单个视频执行全字段抽取。"""
        title = video.get("title", "")
        desc = video.get("description", "")
        full_text = f"{title} {desc}"
        category = video.get("category", "")

        result: Dict[str, Any] = {
            "bvid": video.get("bvid"),
            "title": title,
            # 字段 1: 平台
            "platforms": ["bilibili"],
            # 字段 2: 分类
            "categories": [category] if category else [],
            # 字段 3: 关键实体
            "entities": self._extract_entities(full_text, title),
            # 字段 4: 内容动作类型
            "action_types": self._extract_actions(full_text, category),
            # 字段 5: 数量指标
            "metrics": self._extract_metrics(video),
            # 字段 6: 主题关键词
            "keywords": self._extract_keywords(full_text),
            # 抽取摘要
            "summary": self._generate_summary(video, title, category),
            # 证据溯源
            "evidence": {
                "title": title[:200],
                "description": desc[:300],
                "category": category,
            },
        }
        return result

    def extract_all(self) -> List[Dict]:
        """批量抽取全部视频。"""
        # 先统计全局关键词用于 IDF
        self._all_keywords = Counter()
        for v in self.videos:
            tokens = self._tokenize_jieba(f"{v.get('title','')} {v.get('description','')}")
            self._all_keywords.update(tokens)

        results = []
        for v in self.videos:
            results.append(self.extract_one(v))
        return results

    # ── 子抽取方法 ──────────────────────────────────────────

    @staticmethod
    def _tokenize_jieba(text: str) -> List[str]:
        words = jieba.lcut(text)
        return [w.strip() for w in words if len(w.strip()) > 1]

    def _extract_entities(self, text: str, title: str) -> List[str]:
        """从标题和描述中抽取关键实体（人名、作品名、品牌等）。"""
        entities = []
        lower_text = text.lower()

        for category, terms in self.ENTITY_PATTERNS.items():
            for term in terms:
                if term.lower() in lower_text:
                    entities.append(term)

        # jieba 抽取人名（nr 词性）
        import jieba.posseg as pseg
        for word, flag in pseg.cut(title):
            if flag == "nr" and len(word) > 1 and word not in entities:
                entities.append(word)

        return list(dict.fromkeys(entities))  # 去重保序

    def _extract_actions(self, text: str, category: str) -> List[str]:
        """识别内容动作类型。"""
        actions = []

        # 先看分类名本身是否匹配
        category_lower = category.lower()
        for action, patterns in self.ACTION_PATTERNS.items():
            for pat in patterns:
                if pat.lower() in category_lower:
                    actions.append(action)
                    break

        # 再看标题描述中匹配
        for action, patterns in self.ACTION_PATTERNS.items():
            for pat in patterns:
                if pat in text:
                    actions.append(action)
                    break

        return list(dict.fromkeys(actions))

    @staticmethod
    def _extract_metrics(video: Dict) -> List[Dict[str, str]]:
        """抽取数量指标。"""
        metrics = []
        fields = [
            ("播放", video.get("stat_view", 0), "次"),
            ("点赞", video.get("stat_like", 0), "次"),
            ("投币", video.get("stat_coin", 0), "枚"),
            ("收藏", video.get("stat_favorite", 0), "次"),
            ("弹幕", video.get("stat_danmaku", 0), "条"),
            ("分享", video.get("stat_share", 0), "次"),
            ("评论", video.get("stat_reply", 0), "条"),
            ("时长", video.get("duration_seconds", 0), "秒"),
        ]
        for name, value, unit in fields:
            val = int(value) if value else 0
            if val > 0:
                # 格式化大数字
                if val >= 10000:
                    display = f"{val/10000:.1f}万"
                else:
                    display = str(val)
                metrics.append({
                    "name": name,
                    "value": display,
                    "raw_value": val,
                    "unit": unit,
                })
        return metrics

    def _extract_keywords(self, text: str, top_n: int = 8) -> List[str]:
        """TF-IDF 关键词提取（基于全量语料的 IDF）。"""
        tokens = self._tokenize_jieba(text)
        if not tokens or not self._all_keywords:
            return tokens[:top_n]

        total_docs = len(self.videos)
        tf = Counter(tokens)
        scored = []
        for word, freq in tf.most_common(20):
            df = self._all_keywords.get(word, 1)
            tfidf = freq * math.log(total_docs / (df + 1))
            scored.append((word, tfidf))

        scored.sort(key=lambda x: -x[1])
        return [w for w, _ in scored[:top_n]]

    def _generate_summary(self, video: Dict, title: str, category: str) -> str:
        """生成自然语言摘要。"""
        owner = video.get("owner_name", "未知UP主")
        parts = [f"「{title}」"]

        if category:
            parts.append(f"属于「{category}」分区")
        parts.append(f"由 {owner} 发布")

        view = video.get("stat_view", 0) or 0
        like = video.get("stat_like", 0) or 0
        if view > 0:
            parts.append(f"播放 {self._fmt(view)}")
        if like > 0:
            parts.append(f"点赞 {self._fmt(like)}")

        desc = video.get("description", "") or ""
        if desc:
            parts.append(f"简介: {desc[:50]}")

        return "，".join(parts) + "。"

    @staticmethod
    def _fmt(n: int) -> str:
        if n >= 10000:
            return f"{n/10000:.1f}万"
        return f"{n}"


# ─── 统计报告 ────────────────────────────────────────────────

def generate_report(extractions: List[Dict], videos: List[Dict]) -> Dict:
    """生成抽取统计报告。"""
    total = len(extractions)
    field_stats: Dict[str, Dict] = defaultdict(lambda: {"count": 0, "values": Counter()})

    for ext in extractions:
        for field in ["platforms", "categories", "entities", "action_types", "metrics", "keywords"]:
            values = ext.get(field, [])
            if values:
                field_stats[field]["count"] += 1
            if isinstance(values, list):
                for v in values:
                    if isinstance(v, dict):
                        field_stats[field]["values"][v.get("name", str(v))] += 1
                    else:
                        field_stats[field]["values"][v] += 1

    # 覆盖率
    coverage = {}
    for field, stats in field_stats.items():
        coverage[field] = {
            "count": stats["count"],
            "rate": round(stats["count"] / max(total, 1), 3),
            "top_values": stats["values"].most_common(10),
        }

    # 全局统计
    total_views = sum((v.get("stat_view", 0) or 0) for v in videos)
    total_likes = sum((v.get("stat_like", 0) or 0) for v in videos)
    category_dist = Counter(v.get("category", "未知") for v in videos)

    return {
        "total_videos": total,
        "total_views": total_views,
        "total_likes": total_likes,
        "field_coverage": coverage,
        "category_distribution": category_dist.most_common(),
    }


import math  # noqa: E402 (used in _extract_keywords, import at top is fine)


# ─── CLI ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="多媒体信息抽取")
    parser.add_argument("--data", default="data/bilibili_videos.json", help="数据文件")
    parser.add_argument("--output", default="data/extraction_results.json", help="输出文件")
    parser.add_argument("--report", default="data/extraction_report.json", help="报告文件")
    parser.add_argument("--sample", type=int, default=0, help="展示前 N 条抽取结果")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        data_path = Path(__file__).parent / args.data

    ie = MultimediaIE()
    ie.load_data(data_path)
    extractions = ie.extract_all()

    # 保存
    out_path = Path(args.output) if Path(args.output).is_absolute() else Path(__file__).parent / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(extractions, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 抽取完成: {len(extractions)} 条 → {out_path}")

    # 报告
    report = generate_report(extractions, ie.videos)
    report_path = Path(args.report) if Path(args.report).is_absolute() else Path(__file__).parent / args.report
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✅ 报告: {report_path}")

    # 覆盖率
    print(f"\n📊 字段覆盖率:")
    for field, info in report["field_coverage"].items():
        top_vals = ", ".join(f"{v}({c})" for v, c in info["top_values"][:5])
        print(f"  {field:20s} {info['rate']*100:5.1f}% 热门: {top_vals}")

    if args.sample > 0:
        print(f"\n📋 前 {args.sample} 条抽取结果:")
        for ext in extractions[:args.sample]:
            print(f"\n  ▸ {ext['title'][:50]}")
            print(f"    平台: {ext['platforms']}")
            print(f"    分类: {ext['categories']}")
            print(f"    动作: {ext['action_types']}")
            print(f"    实体: {ext['entities'][:8]}")
            print(f"    关键词: {ext['keywords'][:8]}")
            print(f"    摘要: {ext['summary'][:120]}")
