# Enhanced 变体抽取全流程（逐函数追踪）

> 输入文本: `"SEO Analyzer automates analysis of GitHub repositories"`
> 调用入口: `ie.extract_debug_payload(text, variant="enhanced")`
> 最终产出: `extraction` dict + `debug_payload` dict

---

## 总览：10 层调用链

```
入口 extract_debug_payload
  │
  └─► _extract_text_variant ─── 变体分发
        │
        ├─► _build_text_bundle ─── 文本组装 + 语言判断
        │     ├─► _prepare_focus_text
        │     ├─► _is_english_dominant
        │     │     ├─► _count_ascii_alpha
        │     │     └─► _count_cjk
        │     └─► → bundle {full_text, gliner_text, ...}
        │
        ├─► _predict_gliner_single ─── GLiNER 推理
        │     └─► _predict_gliner_batch
        │           └─► _ensure_gliner_model
        │                 └─► → [{label, text, score, start, end}, ...]
        │
        └─► _extract_structured_enhanced ─── 核心双轨抽取
              │
              ├─► _project_gliner_predictions ─── 预测投影
              │     ├─► _resolve_prediction_offsets
              │     ├─► _resolve_prediction_text
              │     ├─► _context_snippet
              │     ├─► _normalize_span_candidates ─── 多策略规范化
              │     │     ├─► _normalize_to_vocab ─── 四级匹配
              │     │     │     ├─► Level 1: exact_map
              │     │     │     ├─► Level 2: folded_map
              │     │     │     ├─► Level 3: alias_map
              │     │     │     └─► Level 4: fuzzy (edit_distance ≤ 2)
              │     │     ├─► 策略 2: 分隔符拆分
              │     │     ├─► 策略 3: 子串包含
              │     │     └─► 策略 4: 别名子串
              │     └─► → projection {fields: {...}, all_raw_hits: [...]}
              │
              ├─► ENUM_FIELDS 逐字段处理 ─── 循环 5 次
              │     ├─► 分支 A: GLiNER 有产出
              │     │     ├─► state["values"] + state["evidence"]
              │     │     └─► _extract_field_fallback ─── 补充规则匹配
              │     │           ├─► action_types 特殊路径:
              │     │           │     ├─► _extract_keywords_with_normalization
              │     │           │     └─► _expand_action_aliases_with_evidence
              │     │           └─► 其他字段:
              │     │                 └─► _extract_keywords_with_normalization
              │     │                       └─► _normalize_to_vocab (每匹配)
              │     └─► 分支 B: GLiNER 无产出
              │           └─► _extract_field_fallback ─── 全部规则
              │
              └─► metrics 单独处理
                    └─► _extract_metrics_for_enhanced
                          ├─► 无 candidate: _extract_metrics_with_evidence
                          └─► 有 candidate: 逐条正则解析
```

---

## 第 0 层：入口

```
extract_debug_payload(text="SEO Analyzer automates analysis of GitHub repositories",
                      variant="enhanced")
    │
    └─► _extract_text_variant(text="...", variant="enhanced", collect_debug=True)
```

| 参数 | 值 |
|------|-----|
| text | `"SEO Analyzer automates analysis of GitHub repositories"` |
| variant | `"enhanced"` |
| collect_debug | `True` |

---

## 第 1 层：变体分发 `_extract_text_variant`

```
text = "SEO Analyzer automates analysis of GitHub repositories"
variant = "enhanced"
        │
        ├── text 为空? → NO
        ├── variant == "baseline"? → NO
        │
        └── enhanced 路径
              │
              ├─► (a) _build_text_bundle("", "", text, text)
              │       # skill_name=""  category=""  description=原文本  extraction_text=原文本
              │       # extract-one 模式没有文档元数据，全部用原始文本
              │
              ├─► (b) if bundle["gliner_eligible"]:
              │         _predict_gliner_single(bundle["gliner_text"])
              │
              └─► (c) _extract_structured_enhanced(bundle, gliner_predictions, collect_debug=True)
```

---

## 第 2 层：文本包构建 `_build_text_bundle`

```
_build_text_bundle(skill_name="",
                   category="",
                   description="SEO Analyzer automates analysis of GitHub repositories",
                   extraction_text="SEO Analyzer automates analysis of GitHub repositories")
    │
    ├── 步骤 1: full_text
    │       │
    │       └── _normalize_whitespace("  " + "  " + "  " + 原文本)
    │           → "SEO Analyzer automates analysis of GitHub repositories"
    │           # 多余的空白被合并规范化
    │
    ├── 步骤 2: focus_text
    │       │
    │       └── _prepare_focus_text("", "", 原文本, 原文本)
    │             │
    │             ├── _normalize_whitespace("") → ""
    │             ├── _normalize_whitespace("") → ""
    │             ├── _normalize_whitespace("SEO Analyzer ...") → "SEO Analyzer ..."
    │             ├── parts = ["SEO Analyzer automates analysis of GitHub repositories"]
    │             ├── focus_text = "SEO Analyzer automates analysis of GitHub repositories"
    │             │
    │             ├── len(description.split()) = 7 < 40? → YES
    │             │   head = extraction_text[:1400]  → 全文 (长度 < 1400)
    │             │   head.lower().startswith(description.lower()[:80])? → YES
    │             │   # description 和 extraction_text 完全相同，跳过追加避免重复
    │             │
    │             └── → "SEO Analyzer automates analysis of GitHub repositories"
    │
    ├── 步骤 3: 语言判断
    │       │
    │       └── _is_english_dominant("SEO Analyzer automates analysis of GitHub repositories")
    │             │
    │             ├── _count_ascii_alpha(text)
    │             │   re.findall(r"[A-Za-z]", "SEO Analyzer automates analysis of GitHub repositories")
    │             │   → ['S','E','O','A','n','a','l','y','z','e','r','a','u','t','o','m','a','t','e','s',
    │             │       'a','n','a','l','y','s','i','s','o','f','G','i','t','H','u','b','r','e','p','o',
    │             │       's','i','t','o','r','i','e','s']
    │             │   → ascii_letters = 47
    │             │
    │             ├── _count_cjk(text)
    │             │   re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text)
    │             │   → []  →  cjk_chars = 0
    │             │
    │             ├── ascii=47, cjk=0
    │             ├── cjk == 0? → YES → return True
    │             └── → english_dominant = True
    │
    ├── 步骤 4: fallback_text
    │       fallback_text = focus_text (因为 english_dominant=True 且 focus_text 非空)
    │       → "SEO Analyzer automates analysis of GitHub repositories"
    │
    └── 步骤 5: gliner_eligible
            config.gliner.enabled                             → True
            (not config.gliner.english_only_bias or english_dominant)
              = (not True or True) = True
            bool(focus_text)                                  → True
            → gliner_eligible = True
```

### 产物：bundle dict

```json
{
    "full_text":       "SEO Analyzer automates analysis of GitHub repositories",
    "gliner_text":     "SEO Analyzer automates analysis of GitHub repositories",
    "fallback_text":   "SEO Analyzer automates analysis of GitHub repositories",
    "english_dominant": true,
    "gliner_eligible":  true
}
```

> **注意**：本例中 full_text / gliner_text / fallback_text 三者完全相同，因为这是 extract-one 单条模式，没有外部 skill_md 文本和 category 等元数据来区分它们。在全量抽取模式（`extract_all`）中，三者通常不同：
> - `full_text` = skill_name + category + external_skill_text（最长）
> - `gliner_text` = skill_name + category + description（较短，适合 GLiNER 输入）
> - `fallback_text` = focus_text（规则回退用）

---

## 第 3 层：GLiNER 模型加载 `_ensure_gliner_model`

```
_ensure_gliner_model()
    │
    ├── config.gliner.enabled? → True
    ├── _gliner_checked? → False (首次调用)
    │
    ├── _gliner_checked = True
    │
    ├── from gliner import GLiNER  (导入 gliner 库)
    │
    ├── GLiNER.from_pretrained("urchade/gliner_multi-v2.1",
    │       cache_dir="ie_system/runtime/gliner_cache/")
    │   → mdeberta-v3-base 模型加载 (首次 ~2.2GB, 后续命中缓存)
    │
    ├── device = "cpu" → model.to("cpu")
    │
    ├── self._gliner_model = model
    └── → True (加载成功)
```

### 产物：已就绪的 GLiNER 模型

```
model: GLiNER 实例
  arch:      mdeberta-v3-base
  params:    ~580M
  device:    cpu
  vocab:     多语言 tokenizer (支持英文 + 中文 + ...)
  labels:    ["platform or tool", "programming language or framework",
              "action or capability", "target domain or industry",
              "output format or file type", "quantitative metric"]
```

---

## 第 4 层：GLiNER 批量推理 `_predict_gliner_batch`

```
_predict_gliner_single("SEO Analyzer automates analysis of GitHub repositories")
    │
    └── _predict_gliner_batch(["SEO Analyzer automates analysis of GitHub repositories"])
          │
          ├── texts 非空 → 继续
          ├── _ensure_gliner_model() → True (已加载)
          │
          ├── model.batch_predict_entities(
          │       texts=["SEO Analyzer automates analysis of GitHub repositories"],
          │       labels=["platform or tool",
          │               "programming language or framework",
          │               "action or capability",
          │               "target domain or industry",
          │               "output format or file type",
          │               "quantitative metric"],
          │       threshold=0.3,      # _gliner_min_threshold
          │       multi_label=True,    # 同一 span 可属于多个 label
          │       flat_ner=False,      # 允许嵌套实体
          │       batch_size=16
          │   )
          │
          │   ╔══════════════════════════════════════════════════════╗
          │   ║  GLiNER 内部推理 (简化)                            ║
          │   ║                                                    ║
          │   ║  tokens: [SEO, Analyzer, automates, analysis,      ║
          │   ║           of, GitHub, repositories]                ║
          │   ║                                                    ║
          │   ║  mdeberta 编码 → 768 维 token embeddings           ║
          │   ║                                                    ║
          │   ║  对每个可能的 span × 每个 label:                  ║
          │   ║    "GitHub" + "platform or tool"              → 0.92 ✓ ║
          │   ║    "SEO Analyzer" + "target domain"           → 0.68 ✓ ║
          │   ║    "analysis" + "action or capability"        → 0.87 ✓ ║
          │   ║    "automates" + "action or capability"       → 0.41   ║
          │   ║    "SEO Analyzer" + "platform or tool"        → 0.35   ║
          │   ║    "GitHub" + "programming language"          → 0.12 ✗ ║
          │   ║    ... (其他低分组合被 global threshold 0.3 过滤)     ║
          │   ╚══════════════════════════════════════════════════════╝
          │
          └── 返回: [[
                  {"label":"action or capability",
                   "text":"analysis",
                   "score":0.87,
                   "start":26,
                   "end":34},
                  {"label":"platform or tool",
                   "text":"GitHub",
                   "score":0.92,
                   "start":38,
                   "end":44},
                  {"label":"target domain or industry",
                   "text":"SEO Analyzer",
                   "score":0.68,
                   "start":0,
                   "end":12}
                ]]
```

### 产物：gliner_predictions

```python
[
    {"label": "action or capability",      "text": "analysis",      "score": 0.87, "start": 26, "end": 34},
    {"label": "platform or tool",          "text": "GitHub",        "score": 0.92, "start": 38, "end": 44},
    {"label": "target domain or industry", "text": "SEO Analyzer",  "score": 0.68, "start":  0, "end": 12},
]
```

---

## 第 5 层：预测投影 `_project_gliner_predictions`

```
_project_gliner_predictions(text="SEO Analyzer automates analysis of GitHub repositories",
                            predictions=[3条GLiNER结果])
    │
    ├── _empty_gliner_projection() → projection 模板 (6 个字段，每个含 raw_hits/values/evidence/...)
    │
    ├── 逐条处理 3 个预测:
    │
    ├──[预测 1]──────────────────────────────────────────────────
    │   label = "action or capability"
    │   field = _label_to_field["action or capability"]
    │         → "action_types"
    │
    │   _resolve_prediction_offsets(text, {start:26, end:34})
    │   → 验证 0≤26≤34≤53 → 返回 (26, 34) ✓
    │
    │   _resolve_prediction_text(text, ..., 26, 34)
    │   → prediction["text"]="analysis" → 返回 "analysis"
    │
    │   _context_snippet(text, 26, 34)
    │   → text[max(0,26-48):min(53,34+48)] = text[0:53]
    │   → "SEO Analyzer automates analysis of GitHub repositories"
    │
    │   debug_entry = {
    │       field:"action_types", label:"action or capability",
    │       text:"analysis", score:0.87,
    │       start:26, end:34,
    │       context:"SEO Analyzer automates analysis of GitHub repositories"
    │   }
    │   → raw_hits["action_types"].append(debug_entry)
    │
    │   threshold = _gliner_thresholds["action_types"] = 0.5
    │   score 0.87 ≥ 0.5 → 通过
    │   → threshold_hits["action_types"].append(debug_entry)
    │
    │   field != "metrics" → 走规范化路径
    │
    │   ┌── _normalize_span_candidates("analysis", "action_types") ──┐
    │   │                                                              │
    │   │  [策略 1] _normalize_to_vocab("analysis", "action_types")   │
    │   │    │                                                         │
    │   │    ├── _normalize_surface("analysis")                       │
    │   │    │   → lower() → "analysis"                               │
    │   │    │   → translate(引号表) → "analysis" (无变化)             │
    │   │    │   → re.sub(r"\s+", " ") → "analysis"                   │
    │   │    │   → strip(punctuation) → "analysis"                    │
    │   │    │                                                         │
    │   │    ├── Level 1: exact_map                                      │
    │   │    │   _field_exact_maps["action_types"] 包含:             │
    │   │    │     {"analyze":"analyze", "generate":"generate",           │
    │   │    │      "monitor":"monitor", "create":"create", ...}     │
    │   │    │   "analysis" in {"analyze","generate",...}? → NO      │
    │   │    │   # 关键词表存的是动词原形，不匹配名词 "analysis"        │
    │   │    │                                                         │
    │   │    ├── Level 2: folded_map                                     │
    │   │    │   folded = _fold_lookup("analysis")                        │
    │   │    │     → _normalize_surface → "analysis"                  │
    │   │    │     → replace("&","and") → "analysis"                  │
    │   │    │     → re.sub(r"[^a-z0-9+#]+","","analysis") → "analysis"│
    │   │    │   "analysis" in folded_map? → NO                       │
    │   │    │                                                         │
    │   │    ├── Level 3: alias_map ✨ 命中！                            │
    │   │    │   _field_alias_maps["action_types"] 来自 GLiNER 别名:   │
    │   │    │     {"analysis":"analyze", "analytics":"analyze",       │
    │   │    │      "analyzer":"analyze", "generation":"generate",    │
    │   │    │      "evaluation":"evaluate", ...}                      │
    │   │    │   "analysis" in alias_map? → YES!                       │
    │   │    │   → return ("analyze", "alias")                         │
    │   │    │                                                         │
    │   │    └── Level 4: fuzzy (未到达，Level 3 已命中)                │
    │   │                                                              │
    │   │  candidates = [("analyze", "alias")]                         │
    │   │  ↓ candidates 非空 → 立即返回                                │
    │   │  (不需要走策略 2/3/4/5)                                       │
    │   └──────────────────────────────────────────────────────────────┘
    │   返回: [("analyze", "alias")]
    │
    │   normalized="analyze", kind="alias"
    │   kind != "exact"? → YES → rule_source = "gliner_normalized"
    │   extra = {"score":0.87, "normalized_from":"analysis"}
    │
    │   values["action_types"].append("analyze")
    │   evidence["action_types"].append({
    │       field:"action_types", value:"analyze",
    │       rule_source:"gliner_normalized",
    │       pattern_source:"action or capability",
    │       matched_text:"analysis",
    │       context:"SEO Analyzer automates analysis of GitHub repositories",
    │       score:0.87, normalized_from:"analysis"
    │   })
    │   accepted_hits["action_types"].append({
    │       value:"analyze", label:"action or capability",
    │       score:0.87, matched_text:"analysis",
    │       normalization_kind:"alias"
    │   })
    │
    ├──[预测 2]──────────────────────────────────────────────────
    │   label = "platform or tool"
    │   field = "platforms"
    │   offsets: start=38, end=44 → 有效
    │   raw_text = "GitHub", score = 0.92
    │   context = "...of GitHub repositori..."  (48 char window)
    │
    │   → raw_hits["platforms"].append(debug_entry)
    │
    │   threshold = _gliner_thresholds["platforms"] = 0.4
    │   0.92 ≥ 0.4 → 通过
    │   → threshold_hits["platforms"].append(debug_entry)
    │
    │   ┌── _normalize_span_candidates("GitHub", "platforms") ────┐
    │   │                                                            │
    │   │  [策略 1] _normalize_to_vocab("GitHub", "platforms")     │
    │   │    │                                                       │
    │   │    ├── _normalize_surface("GitHub")                       │
    │   │    │   → lower() → "github"                               │
    │   │    │   → translate → "github" (智能引号等均无变化)         │
    │   │    │                                                       │
    │   │    ├── Level 1: exact_map ✨ 命中！                          │
    │   │    │   _field_exact_maps["platforms"] 包含:               │
    │   │    │     {"github":"github", "gitlab":"gitlab",           │
    │   │    │      "slack":"slack", "google":"google", ...}        │
    │   │    │   "github" in exact_map? → YES!                       │
    │   │    │   → return ("github", "exact")                       │
    │   │    │                                                       │
    │   │    └── Level 2-4: 未到达                                  │
    │   │                                                            │
    │   │  candidates = [("github", "exact")]                        │
    │   │  → 立即返回                                                │
    │   └────────────────────────────────────────────────────────────┘
    │   返回: [("github", "exact")]
    │
    │   normalized="github", kind="exact"
    │   _fold_lookup("GitHub")="_fold_lookup("github")="github" → 相等
    │   → rule_source = "gliner_direct" (不需要标记 normalized)
    │   extra = {"score":0.92}
    │
    │   values["platforms"].append("github")
    │   evidence["platforms"].append({
    │       field:"platforms", value:"github",
    │       rule_source:"gliner_direct",
    │       pattern_source:"platform or tool",
    │       matched_text:"GitHub",
    │       context:"...of GitHub repositori...",
    │       score:0.92
    │   })
    │
    ├──[预测 3]──────────────────────────────────────────────────
    │   label = "target domain or industry"
    │   field = "target_domains"
    │   offsets: start=0, end=12 → 有效
    │   raw_text = "SEO Analyzer", score = 0.68
    │   context = "SEO Analyzer automates ..." (48 char window)
    │
    │   → raw_hits["target_domains"].append(debug_entry)
    │
    │   threshold = _gliner_thresholds["target_domains"] = 0.5
    │   0.68 ≥ 0.5 → 通过
    │   → threshold_hits["target_domains"].append(debug_entry)
    │
    │   ┌── _normalize_span_candidates("SEO Analyzer", "target_domains") ──┐
    │   │                                                                     │
    │   │  [策略 1] _normalize_to_vocab("SEO Analyzer", "target_domains")   │
    │   │    │                                                                │
    │   │    ├── _normalize_surface("SEO Analyzer")                          │
    │   │    │   → lower() → "seo analyzer"                                  │
    │   │    │                                                                │
    │   │    ├── Level 1: exact_map                                          │
    │   │    │   "seo analyzer" in exact_map? → NO                           │
    │   │    │   # 词表中没有 "seo analyzer" 这个复合词                        │
    │   │    │                                                                │
    │   │    ├── Level 2: folded_map                                         │
    │   │    │   _fold_lookup("seo analyzer")                                 │
    │   │    │     → "seoanalyzer" (空格被移除)                               │
    │   │    │   "seoanalyzer" in folded_map? → NO                           │
    │   │    │                                                                │
    │   │    ├── Level 3: alias_map                                          │
    │   │    │   "seo analyzer" in alias_map? → NO                           │
    │   │    │   "seoanalyzer" in alias_map? → NO                            │
    │   │    │                                                                │
    │   │    ├── Level 4: fuzzy (编辑距离 ≤ 2)                                │
    │   │    │   len("seoanalyzer")=11 ≥ 5 → 启用 fuzzy                      │
    │   │    │   遍历 _field_folded_allowed_values["target_domains"]:       │
    │   │    │     "seoanalyzer" vs "ecommerce"(9)         → dist=8 > 2 ✗    │
    │   │    │     "seoanalyzer" vs "machinelearning"(15) → dist=8 > 2 ✗    │
    │   │    │     "seoanalyzer" vs "ai"(2)               → dist=11> 2 ✗    │
    │   │    │     "seoanalyzer" vs "seo"(3)              → dist=8 > 2 ✗    │
    │   │    │     "seoanalyzer" vs "nlp"(3)              → dist=8 > 2 ✗    │
    │   │    │     ... 全部候选 → dist > 2                                  │
    │   │    │   → 无最佳匹配                                                │
    │   │    │                                                                │
    │   │    └── → return (None, None)                                       │
    │   │                                                                     │
    │   │  candidates = []  (策略 1 失败)                                      │
    │   │                                                                     │
    │   │  [策略 2] 分隔符拆分                                                 │
    │   │    clean_span = "seo analyzer"                                     │
    │   │    re.split(r"(?:,|/|&|\band\b|\bor\b|\+|with)", "seo analyzer")  │
    │   │    → ["seo analyzer"]   (未被分隔符切分)                              │
    │   │    for part in ["seo analyzer"]:                                   │
    │   │      _normalize_to_vocab("seo analyzer", "target_domains")         │
    │   │      → 同上，Level 1-4 全失败 → (None, None)                        │
    │   │    → 无候选                                                         │
    │   │                                                                     │
    │   │  [策略 3] 子串包含 ✨ 命中！                                           │
    │   │    _field_allowed_values["target_domains"]:                       │
    │   │      (按长度降序排列，长词优先匹配)                                    │
    │   │    for value in ["machine learning","deep learning",               │
    │   │                 "business intelligence","social media",             │
    │   │                 "e-commerce","frontend","backend","education",     │
    │   │                 "ai","seo","nlp","ui",...]:                        │
    │   │                                                                     │
    │   │      "machine learning" → pattern r"(?<![a-z0-9])machine learning(?![a-z0-9])" │
    │   │        .search("seo analyzer")? → NO                               │
    │   │      "deep learning"     → NO                                      │
    │   │      ... (跳过多个候选)                                              │
    │   │      "ai" → .search("seo analyzer")? → NO                          │
    │   │      "seo" → .search("seo analyzer")?                              │
    │   │        # "seo" 是 "seo analyzer" 的前缀吗?                           │
    │   │        # pattern = r"(?<![a-z0-9])seo(?![a-z0-9])"                │
    │   │        # "seo" 后接空格，"a" 不是 [a-z0-9] → negative lookahead 成立  │
    │   │        # → YES, 匹配！                                              │
    │   │      add_candidate("seo", "substring")                             │
    │   │                                                                     │
    │   │  candidates = [("seo", "substring")]                                │
    │   │  → 返回！                                                           │
    │   └─────────────────────────────────────────────────────────────────────┘
    │   返回: [("seo", "substring")]
    │
    │   normalized="seo", kind="substring"
    │   kind != "exact"? → YES → rule_source = "gliner_normalized"
    │   extra = {"score":0.68, "normalized_from":"SEO Analyzer"}
    │
    │   values["target_domains"].append("seo")
    │   evidence["target_domains"].append({
    │       field:"target_domains", value:"seo",
    │       rule_source:"gliner_normalized",
    │       pattern_source:"target domain or industry",
    │       matched_text:"SEO Analyzer",
    │       context:"SEO Analyzer automates ...",
    │       score:0.68, normalized_from:"SEO Analyzer"
    │   })
    │
    └── 收尾: 为每个字段判定 fallback_reason
          for field in EXTRACTED_FIELDS:
              platforms:      raw_hits=1, threshold=1, values=["github"]    → "not_needed"
              languages:      raw_hits=0                                    → "no_hits"
              action_types:   raw_hits=1, threshold=1, values=["analyze"]   → "not_needed"
              target_domains: raw_hits=1, threshold=1, values=["seo"]       → "not_needed"
              output_formats: raw_hits=0                                    → "no_hits"
              metrics:        raw_hits=0                                    → "no_hits"
```

### 产物：projection dict

```json
{
    "fields": {
        "platforms": {
            "raw_hits": [
                {"text":"GitHub","score":0.92,"label":"platform or tool",...}
            ],
            "threshold_hits": [same],
            "values": ["github"],
            "evidence": [
                {"field":"platforms","value":"github","rule_source":"gliner_direct",
                 "matched_text":"GitHub","score":0.92,...}
            ],
            "unknown_evidence": [],
            "accepted_hits": [
                {"value":"github","label":"platform or tool","score":0.92,"matched_text":"GitHub",
                 "normalization_kind":"exact"}
            ],
            "fallback_reason": "not_needed"
        },
        "languages": {
            "raw_hits": [], "threshold_hits": [], "values": [],
            "evidence": [], "unknown_evidence": [], "accepted_hits": [],
            "fallback_reason": "no_hits"
        },
        "action_types": {
            "raw_hits": [
                {"text":"analysis","score":0.87,"label":"action or capability",...}
            ],
            "threshold_hits": [same],
            "values": ["analyze"],
            "evidence": [
                {"field":"action_types","value":"analyze","rule_source":"gliner_normalized",
                 "matched_text":"analysis","score":0.87,"normalized_from":"analysis",...}
            ],
            "unknown_evidence": [],
            "accepted_hits": [
                {"value":"analyze","label":"action or capability","score":0.87,
                 "matched_text":"analysis","normalization_kind":"alias"}
            ],
            "fallback_reason": "not_needed"
        },
        "target_domains": {
            "raw_hits": [
                {"text":"SEO Analyzer","score":0.68,"label":"target domain or industry",...}
            ],
            "threshold_hits": [same],
            "values": ["seo"],
            "evidence": [
                {"field":"target_domains","value":"seo","rule_source":"gliner_normalized",
                 "matched_text":"SEO Analyzer","score":0.68,"normalized_from":"SEO Analyzer",...}
            ],
            "unknown_evidence": [],
            "accepted_hits": [
                {"value":"seo","label":"target domain or industry","score":0.68,
                 "matched_text":"SEO Analyzer","normalization_kind":"substring"}
            ],
            "fallback_reason": "not_needed"
        },
        "output_formats": {
            "raw_hits": [], "threshold_hits": [], "values": [],
            "evidence": [], "unknown_evidence": [], "accepted_hits": [],
            "fallback_reason": "no_hits"
        },
        "metrics": {
            "raw_hits": [], "threshold_hits": [], "values": [],
            "evidence": [], "unknown_evidence": [], "accepted_hits": [],
            "fallback_reason": "no_hits"
        }
    },
    "all_raw_hits": [
        {"text":"analysis","score":0.87,"label":"action or capability",...},
        {"text":"GitHub","score":0.92,"label":"platform or tool",...},
        {"text":"SEO Analyzer","score":0.68,"label":"target domain or industry",...}
    ]
}
```

---

## 第 6 层：Enhanced 核心抽取 `_extract_structured_enhanced`

```
_extract_structured_enhanced(bundle={...}, gliner_predictions=[3条], collect_debug=True)
    │
    ├── extraction = _empty_extraction()
    │   → {platforms:[], languages:[], action_types:[],
    │       target_domains:[], output_formats:[], metrics:[],
    │       evidence: {platforms:[], languages:[], action_types:[],
    │                  target_domains:[], output_formats:[], metrics:[]}}
    │
    ├── debug_payload = _build_gliner_debug_stub(bundle)
    │   → {enabled:True, available:False, used:False, mode:"disabled",
    │       raw_hits:[], normalized_hits:{...}, fallback:{...}, model_error:null}
    │
    ├── gliner_mode = "gliner" (因为 gliner_eligible=True + 模型加载成功)
    ├── gliner_available = True
    ├── projected = _project_gliner_predictions(...) (见第 5 层)
    │
    ├── debug_payload["used"] = True
    ├── debug_payload["available"] = True
    ├── debug_payload["mode"] = "gliner"
    ├── debug_payload["raw_hits"] = projected["all_raw_hits"]
    │
    ├──[ENUM_FIELDS 循环: platforms]───────────────────────────────
    │   state = projected["fields"]["platforms"]  (GLiNER 有产出)
    │
    │   field_evidence.extend(state["unknown_evidence"])  → []
    │   state["values"] = ["github"]  → 非空
    │
    │   → 分支 A: GLiNER 有产出
    │   field_values = ["github"]
    │   field_evidence = [gliner_direct证据]
    │
    │   ┌── _extract_field_fallback("platforms", fallback_text) ────┐
    │   │  field != "action_types" → 通用路径                         │
    │   │  patterns = getattr(self, "_platform_patterns")            │
    │   │    → [(re.compile(r"\bgithub\b"),"github"),               │
    │   │        (re.compile(r"\bgitlab\b"),"gitlab"),               │
    │   │        (re.compile(r"\bslack\b"),"slack"),                 │
    │   │        ... 共 N 个平台关键词]                               │
    │   │                                                              │
    │   │  ┌── _extract_keywords_with_normalization ──┐              │
    │   │  │  for (pattern, _) in patterns:           │              │
    │   │  │    for match in pattern.finditer(text):  │              │
    │   │  │                                           │              │
    │   │  │  pattern r"\bgithub\b".finditer(text):      │              │
    │   │  │    → match "GitHub" (position 38-44)     │              │
    │   │  │    matched_text = "GitHub"                │              │
    │   │  │                                           │              │
    │   │  │    _normalize_to_vocab("GitHub","platforms")           │
    │   │  │      → _normalize_surface → "github"     │              │
    │   │  │      → Level 1 exact_map["github"] → "github" ✓        │
    │   │  │      → ("github", "exact")               │              │
    │   │  │                                           │              │
    │   │  │    "github" not in seen → append          │              │
    │   │  │    evidence.append({                      │              │
    │   │  │      field:"platforms", value:"github",     │              │
    │   │  │      rule_source:"keyword_fallback",       │              │
    │   │  │      pattern_source:"\\bgithub\\b",           │              │
    │   │  │      matched_text:"GitHub",                │              │
    │   │  │      context:"...of GitHub repositori..."  │              │
    │   │  │    })                                      │              │
    │   │  │                                           │              │
    │   │  │  其他 pattern (.gitlab, slack, ...)       │              │
    │   │  │    → 全部无匹配                             │              │
    │   │  └── → values=["github"], evidence=[keyword证据]│         │
    │   └────────────────────────────────────────────────────────────┘
    │   返回: supplement_values=["github"],
    │         supplement_evidence=[keyword_fallback证据]
    │
    │   ┌── _merge_field_values_and_evidence ──┐
    │   │  base_values      = ["github"]       │
    │   │  base_evidence     = [gliner证据]     │
    │   │  supplement_values = ["github"]       │
    │   │  supplement_evidence = [keyword证据]  │
    │   │                                       │
    │   │  seen = {"github"}                    │
    │   │  "github" in seen → 跳过             │
    │   │                                       │
    │   │  → merged_values=["github"],          │
    │   │    merged_evidence=[gliner证据, keyword证据]│
    │   └───────────────────────────────────────┘
    │
    │   extraction["platforms"] = self._dedupe_preserve_order(["github"])
    │                            → ["github"]
    │   evidence["platforms"] = [gliner_direct证据, keyword_fallback证据]
    │
    ├──[ENUM_FIELDS 循环: languages]────────────────────────────────
    │   state = projected["fields"]["languages"]  (全空)
    │
    │   field_evidence.extend(state["unknown_evidence"])  → []
    │   state["values"] = []  → 空
    │
    │   → 分支 B: GLiNER 无产出
    │   fallback_reason = state["fallback_reason"] → "no_hits"
    │
    │   ┌── _extract_field_fallback("languages", fallback_text) ──┐
    │   │  patterns = _language_patterns                            │
    │   │    → [(re.compile(r"\bpython\b"),"python"),              │
    │   │        (re.compile(r"\bjavascript\b"),"javascript"),      │
    │   │        (re.compile(r"\breact\b"),"react"),               │
    │   │        ... 共 N 个语言关键词]                              │
    │   │                                                            │
    │   │  _extract_keywords_with_normalization(...)                │
    │   │    for pattern in [python, javascript, react, vue,       │
    │   │                    go, rust, java, ...]:                  │
    │   │      finditer("SEO Analyzer automates analysis of        │
    │   │                GitHub repositories")                      │
    │   │      → 全都不匹配                                         │
    │   │    → values=[], evidence=[]                               │
    │   └──────────────────────────────────────────────────────────┘
    │   返回: (values=[], evidence=[])
    │
    │   field_values = []
    │   field_evidence = []
    │   extraction["languages"] = []
    │   evidence["languages"] = []
    │
    ├──[ENUM_FIELDS 循环: action_types]─────────────────────────────
    │   state = projected["fields"]["action_types"]  (GLiNER 有产出)
    │
    │   → 分支 A (同 platforms)
    │   field_values = ["analyze"]
    │   field_evidence = [gliner_normalized证据]
    │
    │   ┌── _extract_field_fallback("action_types", fallback_text) ─┐
    │   │  field == "action_types" → 走特殊路径                       │
    │   │                                                              │
    │   │  (a) _extract_keywords_with_normalization()                  │
    │   │      patterns = _action_patterns                           │
    │   │        → [(re.compile(r"\banalyze\b"),"analyze"),          │
    │   │            (re.compile(r"\bgenerate\b"),"generate"),         │
    │   │            (re.compile(r"\bmonitor\b"),"monitor"),          │
    │   │            ... 共 N 个动作关键词]                             │
    │   │      finditer → 原文本中是 "analysis" 和 "automates",       │
    │   │                   不是 "analyze" 或 "monitor"               │
    │   │      → values=[], evidence=[]                               │
    │   │                                                              │
    │   │  (b) _expand_action_aliases_with_evidence()                  │
    │   │      normalize_to_vocab=True                                │
    │   │      seen = {} (keyword 阶段没有产出)                         │
    │   │      expanded = []                                           │
    │   │                                                              │
    │   │      遍历 ACTION_ALIAS_PATTERNS (17 条):                     │
    │   │                                                              │
    │   │      ① pattern: r"\b(?:analysis|analytics|...)\b"          │
    │   │         .finditer(text)                                     │
    │   │         → 找到 "analysis" (position 26-34)                  │
    │   │         canonical_action = "analyze"                        │
    │   │         _normalize_to_vocab("analyze","action_types")       │
    │   │           → exact_map["analyze"] → "analyze" ✓              │
    │   │         value = "analyze"                                   │
    │   │         "analyze" not in seen → append                      │
    │   │         evidence.append({                                   │
    │   │           field:"action_types", value:"analyze",             │
    │   │           rule_source:"alias_fallback",                     │
    │   │           pattern_source:"\\b(?:analysis|analytics|...)\\b",  │
    │   │           matched_text:"analysis",                          │
    │   │           context:"...automates analysis of GitHub..."      │
    │   │         })                                                   │
    │   │                                                              │
    │   │      ② pattern: r"\b(?:automation|automated)\b"            │
    │   │         .finditer(text)                                     │
    │   │         → "automates" 不匹配 "automation" 或 "automated"   │
    │   │         → 跳过                                               │
    │   │                                                              │
    │   │      ③-⑰ 其他 15 条 pattern: 全部无匹配                      │
    │   │                                                              │
    │   │      → expanded=["analyze"], evidence=[alias_fallback证据]   │
    │   └────────────────────────────────────────────────────────────┘
    │   返回: supplement_values=["analyze"],
    │         supplement_evidence=[alias_fallback证据]
    │
    │   _merge: base=["analyze"], supplement=["analyze"]
    │   → "analyze" already in seen → 跳过
    │   → merged=["analyze"], merged_evidence=[gliner证据, alias证据]
    │
    │   extraction["action_types"] = ["analyze"]
    │   evidence["action_types"] = [gliner_normalized, alias_fallback]
    │
    ├──[ENUM_FIELDS 循环: target_domains]───────────────────────────
    │   同 platforms，GLiNER 有产出 → 分支 A
    │
    │   ┌── _extract_field_fallback("target_domains", ...) ──┐
    │   │  _extract_keywords_with_normalization(...)          │
    │   │    patterns = _domain_patterns                      │
    │   │      → [(re.compile(r"\bseo\b"),"seo"),            │
    │   │          (re.compile(r"\be-commerce\b"),"e-commerce"),│
    │   │          ...]                                       │
    │   │    finditer → 如果关键词表中有 "seo":               │
    │   │      → 匹配 "SEO" → normalize → "seo" ✓           │
    │   │      → supplement_values=["seo"], evidence=[...]   │
    │   │    如果关键词表中没有 "seo":                        │
    │   │      → 无匹配 → supplement=[], evidence=[]        │
    │   └────────────────────────────────────────────────────┘
    │
    │   _merge → "seo" already in seen → 跳过去重
    │   extraction["target_domains"] = ["seo"]
    │
    ├──[ENUM_FIELDS 循环: output_formats]───────────────────────────
    │   同 languages，GLiNER 无产出 → 分支 B
    │
    │   ┌── _extract_field_fallback("output_formats", ...) ──┐
    │   │  patterns = _format_patterns                        │
    │   │    → [(re.compile(r"\bjson\b"),"json"),            │
    │   │        (re.compile(r"\bpdf\b"),"pdf"),              │
    │   │        ...]                                         │
    │   │  finditer → 原文本无 "json"/"pdf" 等 → values=[]   │
    │   └────────────────────────────────────────────────────┘
    │
    │   extraction["output_formats"] = []
    │
    ├──[metrics 单独处理]──────────────────────────────────────────
    │   metric_candidates = projected["fields"]["metrics"]["threshold_hits"]
    │                     = []   (GLiNER 没有识别到量化指标)
    │
    │   ┌── _extract_metrics_for_enhanced(text, candidate_hits=[], gliner_mode="gliner") ──┐
    │   │                                                                                    │
    │   │  gliner_mode == "gliner" → YES                                                    │
    │   │  candidate_hits 为空 → YES                                                         │
    │   │                                                                                    │
    │   │  → 回退到全文正则                                                                   │
    │   │  ┌── _extract_metrics_with_evidence(text) ──┐                                    │
    │   │  │  word_to_num = {"two":"2","three":"3",...}│                                    │
    │   │  │                                            │                                    │
    │   │  │  pattern 1: r"(\d+)[\-\s]*(signal|..."    │                                    │
    │   │  │    → 文本无 "5 criteria" 之类 → 0 匹配     │                                    │
    │   │  │                                            │                                    │
    │   │  │  pattern 2: r"(?:across|over|...)\s+"     │                                    │
    │   │  │    → 文本无 "across N dimensions" → 0 匹配 │                                    │
    │   │  │                                            │                                    │
    │   │  │  pattern 3: r"(\d+)\s*[-–—]\s*(\d+)"      │                                    │
    │   │  │    → 0 匹配                                │                                    │
    │   │  │                                            │                                    │
    │   │  │  pattern 4: r"(?:supports?|...)\s+(two..." │                                    │
    │   │  │    → "automates" ≠ "supports" → 0 匹配     │                                    │
    │   │  └── → metrics=[], evidence=[] ──────────────┘                                    │
    │   │                                                                                    │
    │   │  debug_payload = {                                                                  │
    │   │    parsed_metrics: [],                                                              │
    │   │    fallback: {reason:"no_hits", used:True, result_count:0}                         │
    │   │  }                                                                                  │
    │   └────────────────────────────────────────────────────────────────────────────────────┘
    │
    │   extraction["metrics"] = []
    │   evidence["metrics"] = []
    │
    └── collect_debug=True → return (extraction, debug_payload)
```

### 产物：extraction + debug_payload

```json
{
    "extraction": {
        "platforms": ["github"],
        "languages": [],
        "action_types": ["analyze"],
        "target_domains": ["seo"],
        "output_formats": [],
        "metrics": [],
        "evidence": {
            "platforms": [
                {"field":"platforms","value":"github","rule_source":"gliner_direct",
                 "pattern_source":"platform or tool","matched_text":"GitHub",
                 "context":"SEO Analyzer automates analysis of GitHub repositories",
                 "score":0.92},
                {"field":"platforms","value":"github","rule_source":"keyword_fallback",
                 "pattern_source":"\\bgithub\\b","matched_text":"GitHub",
                 "context":"...of GitHub repositori..."}
            ],
            "languages": [],
            "action_types": [
                {"field":"action_types","value":"analyze","rule_source":"gliner_normalized",
                 "pattern_source":"action or capability","matched_text":"analysis",
                 "context":"SEO Analyzer automates analysis of GitHub repositories",
                 "score":0.87,"normalized_from":"analysis"},
                {"field":"action_types","value":"analyze","rule_source":"alias_fallback",
                 "pattern_source":"\\b(?:analysis|analytics|analyzer|analyst)\\b",
                 "matched_text":"analysis",
                 "context":"...automates analysis of GitHub..."}
            ],
            "target_domains": [
                {"field":"target_domains","value":"seo","rule_source":"gliner_normalized",
                 "pattern_source":"target domain or industry","matched_text":"SEO Analyzer",
                 "context":"SEO Analyzer automates analysis of ...",
                 "score":0.68,"normalized_from":"SEO Analyzer"}
            ],
            "output_formats": [],
            "metrics": []
        }
    }
}
```

---

## 第 7 层：debug_payload 组装 `extract_debug_payload`

```
回到 extract_debug_payload:
    │
    ├── evidence_map = extraction["evidence"]
    │
    ├── evidence_count = 0
    │   + len(platforms证据) = 2
    │   + len(languages证据) = 0
    │   + len(action_types证据) = 2
    │   + len(target_domains证据) = 1
    │   + len(output_formats证据) = 0
    │   + len(metrics证据) = 0
    │   = 5
    │
    ├── nonempty_fields = [f for f in EXTRACTED_FIELDS if extraction.get(f)]
    │   → ["platforms", "action_types", "target_domains"]
    │
    └── 最终输出:
```

### 最终产物

```json
{
    "variant": "enhanced",
    "input_text": "SEO Analyzer automates analysis of GitHub repositories",
    "extraction": {
        "platforms": ["github"],
        "languages": [],
        "action_types": ["analyze"],
        "target_domains": ["seo"],
        "output_formats": [],
        "metrics": [],
        "evidence": { /* 见第 6 层产物 */ }
    },
    "evidence": { /* 同上 */ },
    "evidence_count": 5,
    "summary": {
        "nonempty_fields": ["platforms", "action_types", "target_domains"],
        "info_point_count": 3
    },
    "gliner": {
        "enabled": true,
        "available": true,
        "used": true,
        "mode": "gliner",
        "model_name": "urchade/gliner_multi-v2.1",
        "device": "cpu",
        "english_dominant": true,
        "raw_hits": [ /* 3 条 GLiNER 原始预测 */ ],
        "normalized_hits": {
            "platforms": [{"value":"github","label":"platform or tool","score":0.92,"normalization_kind":"exact"}],
            "languages": [],
            "action_types": [{"value":"analyze","label":"action or capability","score":0.87,"normalization_kind":"alias"}],
            "target_domains": [{"value":"seo","label":"target domain or industry","score":0.68,"normalization_kind":"substring"}],
            "output_formats": [],
            "metrics": []
        },
        "fallback": {
            "platforms":      {"reason":"not_needed","used":false,"result_count":1},
            "languages":      {"reason":"no_hits","used":true,"result_count":0},
            "action_types":   {"reason":"not_needed","used":false,"result_count":1},
            "target_domains": {"reason":"not_needed","used":false,"result_count":1},
            "output_formats": {"reason":"no_hits","used":true,"result_count":0},
            "metrics":        {"reason":"no_hits","used":true,"result_count":0}
        },
        "model_error": null
    }
}
```

---

## 决策汇总

| # | 函数 | 决策点 | 条件 | 走的分支 | 结果 |
|---|------|--------|------|---------|------|
| 1 | `_extract_text_variant` | 变体选择 | variant="enhanced" | enhanced 路径 | 走 GLiNER+规则双轨 |
| 2 | `_build_text_bundle` | 语言判断 | 英文, 无中文 | english_dominant=true | GLiNER 不对非英文偏置 |
| 3 | `_build_text_bundle` | GLiNER 资格 | enabled=true, 英文占优, 有文本 | gliner_eligible=true | 启用 GLiNER |
| 4 | `_ensure_gliner_model` | 模型状态 | 首次调用 | 加载模型 | ~2.2GB 缓存命中 |
| 5 | `_predict_gliner_batch` | 全局阈值 | score≥0.3 | "GitHub"/"analysis"/"SEO Analyzer" 通过 | 产出 3 条预测 |
| 6 | `_project_gliner_predictions` | 字段阈值 | platforms=0.4 | "GitHub" 0.92 通过 | 进入规范化 |
| 7 | — | 字段阈值 | action_types=0.5 | "analysis" 0.87 通过 | 进入规范化 |
| 8 | — | 字段阈值 | target_domains=0.5 | "SEO Analyzer" 0.68 通过 | 进入规范化 |
| 9 | `_normalize_to_vocab` | 规范化策略 | "GitHub"→exact_map | Level 1 命中 | "github" (exact) |
| 10 | — | 规范化策略 | "analysis"→alias_map | Level 3 命中 | "analyze" (alias) |
| 11 | — | 规范化策略 | "SEO Analyzer"→全失败 | Level 4 fuzzy 失败 | (None, None) |
| 12 | `_normalize_span_candidates` | 回退策略 | 策略 3 子串 | "seo" ⊂ "SEO Analyzer" | "seo" (substring) |
| 13 | `_extract_structured_enhanced` | 字段分支: platforms | values=["github"] | 分支 A (GLiNER 有产出) | "+ 规则补充" |
| 14 | — | 字段分支: languages | values=[] | 分支 B (GLiNER 无产出) | 纯规则 → 无匹配 |
| 15 | — | 字段分支: action_types | values=["analyze"] | 分支 A | "+ alias 扩展" |
| 16 | — | 字段分支: target_domains | values=["seo"] | 分支 A | "+ 规则补充" |
| 17 | — | 字段分支: output_formats | values=[] | 分支 B | 纯规则 → 无匹配 |
| 18 | `_extract_metrics_for_enhanced` | metrics 处理 | candidates=[] | 回退全文正则 | 4 个正则全无匹配 |
| 19 | `_merge_field_values_and_evidence` | 合并去重 | GLiNER 结果 ∩ 规则结果 | 去重 | 无重复值 |

---

## 补充：全量抽取模式（`extract_all`）的差异

上述流程是针对 `extract-one` 模式的。在全量抽取模式中，`_build_text_bundle` 的三个文本通常不同：

```
skill_name:      "SEO Analyzer"
category:        "SEO"
description:     "Analyzes SEO data across platforms..."
extraction_text: (来自 data/skill_md/ 的完整 markdown，数百行)

_build_text_bundle 产物:
  full_text:     "SEO Analyzer | SEO | [完整技能 markdown]"
                 → 可能数千字，用于 keyword_fallback 规则匹配
  gliner_text:   "SEO Analyzer | SEO | Analyzes SEO data..."
                 → 较短 (~200字)，用于 GLiNER 推理
  fallback_text: 同上
  gliner_eligible: 取决于 _prepare_focus_text 的判断
```

全量抽取还多了一层批量优化：
- `_prepare_document_inputs()` 预处理所有文档 → `prepared_docs`
- 收集所有 `gliner_eligible` 的文档索引 → `eligible_indices`
- **一次** `_predict_gliner_batch(eligible_texts)` → 批量推理
- `predictions_by_index` 按索引分发 → 逐条 `_extract_structured_enhanced`
