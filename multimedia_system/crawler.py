"""B站热门视频爬虫 — 从 Bilibili API 爬取视频元数据与封面图片。"""
from __future__ import annotations

import json
import time
import hashlib
from pathlib import Path
from typing import Dict, List

import requests

API_POPULAR = "https://api.bilibili.com/x/web-interface/popular"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.bilibili.com/",
}


def fetch_popular(ps: int = 50, pn: int = 1) -> List[Dict]:
    """从 B站热门接口获取视频列表。"""
    resp = requests.get(API_POPULAR, params={"ps": ps, "pn": pn}, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"API 错误: code={data.get('code')}, msg={data.get('message')}")
    return data["data"]["list"]


def download_image(url: str, save_path: Path) -> bool:
    """下载图片到本地，返回是否成功。"""
    if save_path.exists():
        return True
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        save_path.write_bytes(resp.content)
        return True
    except Exception as e:
        print(f"  ⚠ 图片下载失败: {url[:60]}... {e}")
        return False


def normalize_video(raw: Dict, covers_dir: Path) -> Dict:
    """将 B站 API 原始数据标准化为统一格式。"""
    vid = raw["bvid"]
    cover_url = raw.get("pic", "")
    cover_filename = f"{vid}.jpg" if cover_url else ""
    cover_local = str(covers_dir / cover_filename) if cover_filename else ""

    stat = raw.get("stat", {})
    owner = raw.get("owner", {})

    pubdate = raw.get("pubdate", 0)
    if pubdate:
        from datetime import datetime
        pubdate_str = datetime.fromtimestamp(pubdate).strftime("%Y-%m-%d %H:%M")
    else:
        pubdate_str = ""

    duration = raw.get("duration", 0)

    return {
        "bvid": vid,
        "aid": raw.get("aid", 0),
        "title": raw.get("title", ""),
        "description": raw.get("desc", ""),
        "cover_url": cover_url,
        "cover_local": cover_local,
        "category": raw.get("tname", ""),
        "duration_seconds": duration,
        "duration_display": f"{duration // 60}:{duration % 60:02d}",
        "publish_date": pubdate_str,
        "owner_name": owner.get("name", ""),
        "owner_mid": owner.get("mid", 0),
        "owner_face": owner.get("face", ""),
        "stat_view": stat.get("view", 0),
        "stat_danmaku": stat.get("danmaku", 0),
        "stat_reply": stat.get("reply", 0),
        "stat_favorite": stat.get("favorite", 0),
        "stat_coin": stat.get("coin", 0),
        "stat_share": stat.get("share", 0),
        "stat_like": stat.get("like", 0),
    }


def crawl(target_count: int = 50, data_dir: Path | None = None) -> Path:
    """主入口：爬取 target_count 条视频数据并返回数据文件路径。"""
    if data_dir is None:
        data_dir = Path(__file__).parent / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    covers_dir = data_dir / "covers"
    covers_dir.mkdir(parents=True, exist_ok=True)

    output_file = data_dir / "bilibili_videos.json"

    print(f"🎬 开始爬取 B站热门视频，目标 {target_count} 条...")
    all_videos: List[Dict] = []
    pn = 1

    while len(all_videos) < target_count:
        batch_size = min(50, target_count - len(all_videos))
        print(f"  请求第 {pn} 页 (ps={batch_size})...")
        try:
            raw_list = fetch_popular(ps=batch_size, pn=pn)
        except Exception as e:
            print(f"  ✗ 第 {pn} 页请求失败: {e}")
            break

        for raw in raw_list:
            video = normalize_video(raw, covers_dir)
            all_videos.append(video)
            print(f"  ✓ [{len(all_videos):3d}] {video['title'][:50]}... ({video['category']})")

        pn += 1
        time.sleep(0.8)  # 礼貌间隔

    # 保存数据
    output_file.write_text(
        json.dumps(all_videos, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n✅ 数据已保存: {output_file} ({len(all_videos)} 条)")

    # 下载封面图片
    print(f"\n🖼  下载封面图片到 {covers_dir} ...")
    success = 0
    for v in all_videos:
        if v["cover_url"]:
            save_path = covers_dir / f"{v['bvid']}.jpg"
            if download_image(v["cover_url"], save_path):
                success += 1
                if success % 10 == 0:
                    print(f"  已下载 {success}/{len(all_videos)} ...")
                time.sleep(0.3)

    print(f"✅ 封面下载完成: {success}/{len(all_videos)}")
    return output_file


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="B站视频爬虫")
    parser.add_argument("--count", type=int, default=50, help="目标数量 (默认 50)")
    parser.add_argument("--data-dir", type=str, default=None, help="数据目录")
    args = parser.parse_args()
    crawl(target_count=args.count)
