# IE 系统信息抽取说明

## 概述

IE 系统（`ie_system/`）是一个**基于规则的信息抽取系统**（Rule-based Information Extraction），从技能描述文本中抽取出平台、语言、动作类型、目标领域、输出格式、指标等结构化信息。核心代码位于 `ie_system/src/skills_ie/extractor.py` 中的 `SkillsIESystem` 类。

---

## 1. 抽取字段

系统从每个技能文档中抽取 6 个结构化字段，组合成一个"事件"（event）：

| 字段 | 说明 | 示例 |
|------|------|------|
| `platforms` | 目标平台/工具 | github, docker, aws, douyin |
| `languages` | 使用的技术/语言/框架 | python, react, pytorch, postgresql |
| `action_types` | 技能执行的动作类型 | generate, analyze, scrape, deploy |
| `target_domains` | 服务的目标领域 | seo, finance, ai, cybersecurity |
| `output_formats` | 支持的输出格式 | json, csv, pdf, mp4, png |
| `metrics` | 量化指标（数值+量纲） | 5-signal, 8-dimension, 1-10 scale |

所有字段抽取结果组合在一起构成事件摘要，例如：

> [market-research-report] 能够 analyze/generate，服务于 marketing/e-commerce 领域，支持 github 平台，使用 python 技术，输出 json 格式。

---

## 2. 抽取算法：三层正则匹配

### 第一层：精确关键词匹配 (`exact_keyword`)

每个字段维护一个关键词列表（在 `ie_system/configs/ie_config.json` 中配置），用词边界正则 `\bkeyword\b` 进行精确匹配：

```
pattern = re.compile(r"\bkeyword\b", re.IGNORECASE)
```

当前各字段关键词规模：

| 字段 | 关键词数量 |
|------|-----------|
| `platforms` | ~35 个 |
| `languages` | ~45 个 |
| `action_types` | ~32 个 |
| `target_domains` | ~35 个 |
| `output_formats` | ~25 个 |

### 第二层：动作别名扩展 (`alias_pattern`) — "enhanced" 变体专属

系统支持两种变体：

- **baseline**：仅使用第一层精确关键词匹配
- **enhanced**：在 baseline 基础上叠加动作别名扩展

`ACTION_ALIAS_PATTERNS` 定义了 16 组动作别名映射，解决同一动作的多种词形变体问题：

| 正则模式 | 归一化动作 |
|---------|-----------|
| `analysis\|analytics\|analyzer\|analyst` | `analyze` |
| `optimization\|optimizer\|optimized` | `optimize` |
| `generation\|generator\|generated` | `generate` |
| `creation\|creator\|writing\|writer\|drafting` | `create` |
| `visualization\|visualizer` | `visualize` |
| `validation\|validator` | `validate` |
| `detection\|detector` | `detect` |
| `comparison\|comparator` | `compare` |
| `automation\|automated` | `automate` |
| `translation\|translator` | `translate` |
| `scheduling\|scheduler` | `schedule` |
| `monitoring` | `monitor` |
| `reviewer\|reviewing` | `review` |
| `extraction\|extractor` | `extract` |
| `parsing\|parser` | `parse` |
| `evaluation\|evaluator` | `evaluate` |

例如：描述中出现 "analytics"、"analyzer" 或 "analyst" 都会被统一映射并加入到 `action_types` 的 `analyze`。

### 第三层：指标数值抽取 (`metric_regex`)

`metrics` 字段不使用简单关键词列表，而是 4 个复杂正则模式：

1. **数字+量纲直接模式**：
   ```
   (\d+)[\-\s]*(signal|criteria|item|point|step|dimension|layer|level|module|metric|check|rule|test|factor)
   ```
   匹配：`5-signal`, `12-criteria`, `3-factor`, `8-dimension`

2. **"跨越/覆盖"模式**：
   ```
   (?:across|over|with|covering|spanning)\s+(\d+)\s+([\w\-]+)
   ```
   匹配：`across 8 dimensions`, `covering 5 layers`

3. **数值范围模式**：
   ```
   (\d+)\s*[-–—]\s*(\d+)\s*(?:scale|score|range|rating)
   ```
   匹配：`1-10 scale`, `0-100 rating`

4. **英文数字模式**：
   ```
   (?:supports?|covers?|includes?)\s+(two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)\s+([\w\-]+)
   ```
   匹配：`supports five modules`，英文数字自动转换为阿拉伯数字。

---

## 3. 证据链保留机制

系统在抽取每个字段的同时，会记录完整的证据链，方便人工复核和误差分析：

```json
{
  "field": "platforms",
  "value": "github",
  "rule_source": "exact_keyword",
  "pattern_source": "\\bgithub\\b",
  "matched_text": "GitHub",
  "context": "…publish directly to GitHub Pages…"
}
```

每条证据包含：
- `field`：所属字段
- `value`：抽取到的值
- `rule_source`：规则来源（`exact_keyword` / `alias_pattern` / `metric_regex`）
- `pattern_source`：命中的正则表达式
- `matched_text`：实际匹配的原始文本
- `context`：命中位置前后 48 字符的上下文片段

---

## 4. 外部语料增强

系统在抽取时并非只使用 `skills_data.json` 中的 `description` 字段，而是按优先级尝试获取更完整的文本：

```
优先级: external_skill_text > skill_md_raw_text > skill_md > description
```

其中 `external_skill_text` 来自 `data/skill_md/` 目录下的完整 SKILL.md 文件，文本更长、信息更丰富，能显著提升规则覆盖率。

---

## 5. 评测体系

### 自动评估（Precision / Recall / F1）

命令：
```bash
python ie_system/skills_ie_system.py evaluate --variant enhanced
```

逐字段对比抽取结果与 `eval/ground_truth.json` 人工标注：

```
TP = expected_set ∩ extracted_set
Precision = TP / |extracted|       # 抽出来的有多少是对的
Recall    = TP / |expected|        # 该抽的有多少被抽到了
F1        = 2 × P × R / (P + R)   # 调和平均
```

评测覆盖字段：`platforms, languages, action_types, target_domains, output_formats`

> 注意：`metrics` 字段因为是 `[{value, unit}]` 字典列表结构，未纳入自动评估。

输出包含：
- **Overall**: 跨字段平均 P/R/F1
- **Field Metrics**: 每个字段的 avg_precision / avg_recall / avg_f1
- **Per Case**: 每个 skill-字段组合的详细 P/R/F1

### 人工评估

提供三级标注体系：`correct` / `partial` / `incorrect`

准确率计算公式：
```
accuracy = (correct + 0.5 × partial) / total
```

结果按字段汇总，存到 `runtime/ie_manual_judgments.json`。

### 变体对比

```bash
python ie_system/skills_ie_system.py compare --eval-set ground_truth.json
```

同时运行 baseline 和 enhanced，计算每个字段的 delta：
```
dP = enhanced.P - baseline.P
dR = enhanced.R - baseline.R
dF1 = enhanced.F1 - baseline.F1
```

对比报告同时输出终端表格和 Markdown 文件（`docs/ie_experiment_materials.md`），量化动作别名扩展带来的提升。

---

## 6. CLI 命令一览

| 命令 | 说明 |
|------|------|
| `extract --variant enhanced` | 对全量数据集执行抽取 |
| `extract-one "text" --variant enhanced` | 对单条文本执行抽取（调试用） |
| `search "keyword" --field platforms` | 在抽取结果中检索 |
| `evaluate --variant enhanced --eval-set ground_truth.json` | 自动评估 |
| `compare --eval-set ground_truth.json` | baseline vs enhanced 对比 |
| `report --variant enhanced` | 生成覆盖率/值分布/证据统计报告 |
| `serve-web --port 5001` | 启动 Web UI |

---

## 7. 关键文件

| 文件 | 作用 |
|------|------|
| `ie_system/skills_ie_system.py` | 系统入口脚本 |
| `ie_system/src/skills_ie/extractor.py` | 核心抽取引擎 |
| `ie_system/src/skills_ie/evaluation.py` | 自动+人工评估模块 |
| `ie_system/src/skills_ie/config.py` | 配置加载 |
| `ie_system/src/skills_ie/cli.py` | 命令行入口 |
| `ie_system/src/skills_ie/web.py` | Flask Web UI |
| `ie_system/configs/ie_config.json` | 关键词配置 |
| `ie_system/eval/ground_truth.json` | 人工标注评测集 |
| `ie_system/output/extraction_results.json` | 抽取结果输出 |
| `ie_system/runtime/` | 报告与状态文件 |
