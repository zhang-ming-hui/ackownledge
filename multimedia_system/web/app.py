"""多媒体检索与抽取系统 — Flask Web 前端。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# 允许从父目录导入 ir_engine / ie_engine
sys.path.insert(0, str(Path(__file__).parent.parent))

from flask import Flask, jsonify, render_template, request

from ir_engine import MultimediaIR
from ie_engine import MultimediaIE, generate_report


def create_app() -> Flask:
    app = Flask(__name__)

    data_dir = Path(__file__).parent.parent / "data"
    videos_file = data_dir / "bilibili_videos.json"
    extractions_file = data_dir / "extraction_results.json"

    # 加载数据
    videos = json.loads(videos_file.read_text(encoding="utf-8"))
    extractions = json.loads(extractions_file.read_text(encoding="utf-8")) if extractions_file.exists() else []

    # 构建提取映射 {bvid: extraction}
    ext_map = {e["bvid"]: e for e in extractions}

    # 构建 IR 索引
    ir = MultimediaIR()
    ir.build_index(videos)

    # 构建 IE 报告
    ie = MultimediaIE()
    ie.load_data(videos_file)
    report = generate_report(extractions, videos) if extractions else {}

    # ── 页面 ───────────────────────────────────────────────

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            videos=videos,
            report=report,
            total=len(videos),
        )

    # ── API ────────────────────────────────────────────────

    @app.get("/api/videos")
    def api_videos():
        """返回视频列表（支持分类过滤）。"""
        cat = request.args.get("category", "").strip()
        if cat:
            filtered = [v for v in videos if v.get("category") == cat]
        else:
            filtered = videos
        return jsonify({"count": len(filtered), "videos": filtered})

    @app.get("/api/video/<bvid>")
    def api_video_detail(bvid: str):
        """返回单个视频的完整信息（含抽取和原始数据）。"""
        video = next((v for v in videos if v["bvid"] == bvid), None)
        if not video:
            return jsonify({"error": "not found"}), 404
        extraction = ext_map.get(bvid, {})
        return jsonify({"video": video, "extraction": extraction})

    @app.get("/api/search")
    def api_search():
        """IR 搜索：文本检索 + 可选图片检索。"""
        query = request.args.get("q", "").strip()
        mode = request.args.get("mode", "hybrid")  # hybrid | text | image
        top_k = int(request.args.get("top_k", "10"))
        min_score = float(request.args.get("min_score", "0.0"))

        if not query:
            return jsonify({"results": [], "query": ""})

        if mode == "image":
            tw, bw, iw = 0.0, 0.0, 1.0
        elif mode == "text":
            tw, bw, iw = 0.5, 0.5, 0.0
        else:
            tw, bw, iw = 0.35, 0.35, 0.30

        results = ir.search(query, top_k=top_k,
                           tfidf_weight=tw, bm25_weight=bw, image_weight=iw,
                           min_score=min_score)
        return jsonify({"results": results, "query": query, "mode": mode})

    @app.get("/api/search-image")
    def api_search_image():
        """纯图片检索（用文字描述搜封面图）。"""
        query = request.args.get("q", "").strip()
        top_k = int(request.args.get("top_k", "10"))
        min_score = float(request.args.get("min_score", "0.0"))
        if not query:
            return jsonify({"results": [], "query": ""})

        results = ir.search(query, top_k=top_k,
                           tfidf_weight=0.0, bm25_weight=0.0, image_weight=1.0,
                           min_score=min_score)
        return jsonify({"results": results, "query": query, "mode": "image"})

    @app.get("/api/extract/<bvid>")
    def api_extract_one(bvid: str):
        """重新抽取单个视频。"""
        video = next((v for v in videos if v["bvid"] == bvid), None)
        if not video:
            return jsonify({"error": "not found"}), 404
        extraction = ie.extract_one(video)
        return jsonify(extraction)

    @app.get("/api/report")
    def api_report():
        return jsonify(report)

    @app.get("/api/categories")
    def api_categories():
        """返回分类列表及计数。"""
        from collections import Counter
        cats = Counter(v.get("category", "未知") for v in videos)
        return jsonify([{"name": k, "count": v} for k, v in cats.most_common()])

    # 封面图片服务
    @app.get("/covers/<filename>")
    def serve_cover(filename: str):
        from flask import send_from_directory
        return send_from_directory(str(data_dir / "covers"), filename)

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "videos": len(videos), "extractions": len(extractions)})

    return app


def serve_web(host: str = "127.0.0.1", port: int = 5002, debug: bool = False):
    app = create_app()
    print(f"\n🎬 多媒体检索与抽取系统")
    print(f"   地址: http://{host}:{port}")
    print(f"   数据: {app.config.get('VIDEO_COUNT', '?')} 个视频")
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="多媒体检索与抽取 Web 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5002)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    serve_web(host=args.host, port=args.port, debug=args.debug)
