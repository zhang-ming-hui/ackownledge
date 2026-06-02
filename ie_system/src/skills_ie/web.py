"""
IE 抽取系统的 Flask Web 页面与 API。

提供基于 Flask 的 Web 界面用于：
  1. 主页（/）         — 搜索已抽取结果、查看字段覆盖率和评估指标
  2. API: /api/extract — 对任意文本执行 ie.extract_debug_payload() 并返回完整详细结果
  3. API: /api/search   — 搜索已抽取结果（支持按字段过滤）
  4. API: /api/judge    — 提交人工判断（correct / incorrect / partial）
  5. API: /api/report   — 返回系统的 report JSON
  6. Health: /healthz   — 健康检查端点

启动方式：
  python ie_system/skills_ie_system.py serve-web --port 5001

部署注意事项：
  - Flask 内置服务器仅适合开发调试，生产环境应使用 gunicorn 等 WSGI 服务器
  - 启动时即加载全部数据并执行抽取，内存占用与数据集大小成正比
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from flask import Flask, jsonify, render_template, request

from .config import IEConfig, load_config
from .extractor import SkillsIESystem
from .evaluation import (
    compute_manual_metrics,
    evaluate_extraction,
    load_manual_judgments,
    save_manual_judgment,
)
from .state import load_json


def create_app(config_path: Path | None = None) -> Flask:
    """
    创建 IE Web 应用并注册页面与 API 路由。
    
    启动时即完成：
      1. 加载配置
      2. 加载数据集
      3. 执行全量抽取（extract_all）
    
    这意味着 / 页面可直接展示字段覆盖率等统计信息。
    """
    config = load_config(config_path)
    app = Flask(__name__, template_folder="templates")

    # 预加载并完成抽取
    default_variant = "api" if config.remote_llm.enabled else "enhanced"
    ie = SkillsIESystem(config, variant=default_variant)
    ie.load_data()
    ie.extract_all()

    # ── 页面路由 ─────────────────────────────────────────────

    @app.get("/")
    def index():
        """
        主页面：搜索已抽取结果 + 展示统计概览。
        
        查询参数：
          q      — 搜索关键词
          field  — 可选的字段过滤
          top_k  — 返回结果数（默认 10，上限 50）
        
        页面数据还包括：
          - report：字段覆盖率 / 值分布 / 证据统计
          - manual_metrics：人工评价准确率
          - auto_eval：自动评估报告（若 ground_truth.json 存在）
        """
        query = request.args.get("q", "").strip()
        field = request.args.get("field", "").strip() or None
        top_k = request.args.get("top_k", "10").strip()
        try:
            top_k_value = max(1, min(int(top_k), 50))
        except ValueError:
            top_k_value = 10

        # 有查询词时才搜索
        results = ie.search_extractions(query, field=field, top_k=top_k_value) if query else []

        # 抽取报告提供字段覆盖率、值分布和证据统计，是页面概览的重要数据源
        report = ie.generate_report()

        # 人工评价数据
        manual_data = load_manual_judgments(config)
        manual_metrics = manual_data.get("summary", {})

        # 自动评估（需要 ground truth 文件存在）
        auto_eval = {}
        gt_path = config.resolve_eval_path(None)
        if gt_path.exists():
            auto_eval = evaluate_extraction(ie.extraction_results, gt_path)

        return render_template(
            "ie_search.html",
            query=query,
            field=field or "",
            top_k=top_k_value,
            results=results,
            report=report,
            manual_metrics=manual_metrics,
            auto_eval=auto_eval,
            total_docs=len(ie.documents),
            total_extractions=len(ie.extraction_results),
        )

    # ── API 路由 ──────────────────────────────────────────────

    @app.get("/api/extract")
    def api_extract():
        """
        对输入文本执行增强抽取，返回完整调试信息。
        
        查询参数：
          text — 要抽取的原始文本
        
        返回 extract_debug_payload() 的结果（含 extraction + evidence + gliner debug）。
        用于测试单条文本的抽取效果。
        """
        text = request.args.get("text", "").strip()
        variant = request.args.get("variant", "").strip() or ie.variant
        if not text:
            return jsonify({"error": "missing text parameter"}), 400
        result = ie.extract_debug_payload(text, variant=variant)
        return jsonify(result)

    @app.get("/api/search")
    def api_search():
        """
        搜索已抽取结果（JSON API）。
        
        查询参数：
          q      — 搜索关键词
          field  — 可选的字段过滤
          top_k  — 返回结果数
        
        返回匹配的抽取事件，含 match_score 排序。
        """
        query = request.args.get("q", "").strip()
        field = request.args.get("field", "").strip() or None
        top_k = request.args.get("top_k", "10").strip()
        try:
            top_k_value = max(1, min(int(top_k), 50))
        except ValueError:
            top_k_value = 10

        results = ie.search_extractions(query, field=field, top_k=top_k_value) if query else []
        return jsonify({
            "query": query,
            "field": field,
            "top_k": top_k_value,
            "result_count": len(results),
            "results": results,
        })

    @app.post("/api/judge")
    def api_judge():
        """
        接收一条人工抽取判断。
        
        POST JSON body:
          {
            "skill_name": "...",
            "field": "action_types",
            "value": "...",
            "label": "correct" | "incorrect" | "partial"
          }
        
        返回更新后的评估汇总。
        label 必须是三个有效值之一，否则返回 400。
        """
        body = request.get_json(silent=True) or {}
        skill_name = body.get("skill_name", "").strip()
        field = body.get("field", "").strip()
        label = body.get("label", "").strip()
        value = body.get("value", "").strip()

        if not skill_name or not field or label not in ("correct", "incorrect", "partial"):
            return jsonify({"ok": False, "error": "invalid input"}), 400

        summary = save_manual_judgment(config, skill_name, field, label, value)
        return jsonify({"ok": True, "summary": summary})

    @app.get("/api/report")
    def api_report():
        """
        返回完整的抽取报告 JSON。
        
        包含：字段覆盖率、值分布 Top-K、信息点分布、可解释性统计。
        """
        return jsonify(ie.generate_report())

    # ── 健康检查 ─────────────────────────────────────────────

    @app.get("/healthz")
    def healthz():
        """
        健康检查端点。
        
        返回系统状态：是否可服务、已加载文档数、已抽取文档数。
        可用于监控和负载均衡探测。
        """
        return jsonify({
            "ok": True,
            "document_count": len(ie.documents),
            "extraction_count": len(ie.extraction_results),
        })

    return app


def serve_web(
    config_path: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 5001,
    debug: bool = False,
) -> None:
    """
    启动 IE Web 服务。
    
    参数：
      config_path — 配置文件路径（None = 默认）
      host        — 绑定的 IP 地址
      port        — 服务端口（默认 5001，与 IR 的 5000 错开）
      debug       — 是否启用 Flask debug 模式
    """
    app = create_app(config_path)
    app.run(host=host, port=port, debug=debug)
