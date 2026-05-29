使用gliner的流程图

    输入: bundle (文本包) + gliner_predictions (可选)
                        │
                        ▼
       ┌─ gliner_eligible? ──→ NO ──→ 全部字段走 fallback (纯规则) ──→ 输出
       │                │
       │               YES
       │                │
       │         _ensure_gliner_model() 加载模型
       │                │
       │    _project_gliner_predictions() 投影到字段
       │                │
       │       ┌────────┴────────┐
       │       │                 │
       │   GLiNER 命中        GLiNER 未命中
       │       │                 │
       │   取 values          fallback_reason:
       │   + 补充规则匹配      no_hits / below_threshold
       │   (_merge)           / normalization_failed
       │       │                 │
       │       └────────┬────────┘
       │                │
       │         ENUM_FIELDS 逐个处理完成
       │                │
       │         metrics 单独处理:
       │         candidate_hits → _extract_metrics_for_enhanced
       │                │
       └────────────────┴──────→ 输出 extraction + debug_payload

一条文本的完整处理路径（以 "SEO Analyzer for GitHub" 为例）


    输入 text = "SEO Analyzer automates analysis of GitHub repositories"
             │
             ▼
    _build_text_bundle → {full_text: "...", gliner_text: "...", english_dominant: true, gliner_eligible: true}
             │
             ▼
    _predict_gliner_single("SEO Analyzer automates analysis of GitHub repositories")
      → GLiNER 返回:
        [{label:"action or capability", text:"analysis", score:0.87},
         {label:"platform or tool",     text:"GitHub",   score:0.92}]
             │
             ▼
    _project_gliner_predictions:
      "analysis" → field=action_types → _normalize_span_candidates → _normalize_to_vocab
        → exact_map["analysis"] → 无
        → folded_map["analysis"] → 无
        → alias_map["analysis"] → "analyze" ✓ → rule_source="gliner_normalized"
      "GitHub" → field=platforms → _normalize_to_vocab
        → exact_map["github"] ✓ → rule_source="gliner_direct"
             │
             ▼
    _extract_structured_enhanced:
      action_types: values=["analyze"] → field_fallback 补充 → keywords+aliases → ...
      platforms:    values=["github"]  → field_fallback 补充 → ...
      metrics:      candidate_hits 为空 → 全文正则 "repositories" 不匹配 → []
             │
             ▼
    最终 extraction:
      {platforms:["github"], action_types:["analyze"], metrics:[],
       evidence: {platforms:[{rule_source:"gliner_direct",...}],
                  action_types:[{rule_source:"gliner_normalized","normalized_from":"analysis",...}]}}