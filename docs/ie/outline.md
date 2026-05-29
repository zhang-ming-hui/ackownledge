# IE 实验报告提纲

## 1. 引言
- 任务定义：从技能描述里抽取 `platforms / languages / action_types / target_domains / output_formats / metrics`。
- 应用场景：技能检索后的结构化展示、统计分析、后续问答或推荐。
- 数据集概况：1000 条 skill 记录，中英混合但英文占绝对多数，`SKILL.md` 外置保存。
- 实验目标：比较 baseline、regex+alias、GLiNER 三阶段策略。

## 2. 数据获取与预处理
- `paqu.py` 抓取与 checkpoint 流程图。
- 字段说明：主字段 + `skill_md_*_path` 外置文本。
- 预处理：优先读取外置 `SKILL.md`，构造 `full_text / gliner_text / fallback_text`，按英文字母与 CJK 数量做语言偏置判断。

## 3. 核心算法
- 三个 variant 的关系：baseline -> enhanced-regex -> enhanced-gliner。
- baseline：精确关键字 + metrics 正则。
- enhanced-regex：受控词表归一化、action alias 扩展、fallback 规则。
- enhanced-gliner：语言检测 -> GLiNER 推理 -> 阈值过滤 -> 词表归一化 -> fallback。
- 归一化逻辑：exact -> folded -> alias -> fuzzy -> unknown。
- 阈值表：`platforms=0.4`、`languages=0.3`、`action_types=0.5`、`target_domains=0.5`、`output_formats=0.3`、`metrics=0.6`。
- 伪代码：增强版抽取流程。

## 4. 实验设计与过程
- 实验环境：Windows 10，conda `yolov82`，Python 3.11.5，GLiNER 在 CPU 上运行。
- 标注集：`ground_truth.json` 共 10 条 skill，自动评测只看 5 个枚举字段，`metrics` 不参与。
- 当前数据快照说明：标注中的 `pdf-converter` 不在现有 `skills_data.json` 里，所以自动评测实际匹配 9 条。
- 命令与输出：`extract`、`evaluate`、`compare`、`report`，输出到 `ie_system/output/` 与 `ie_system/runtime/`。

## 5. 实验结果与对比分析
- 三阶段总表：baseline / enhanced-regex / enhanced-gliner 的 P、R、F1。
- 分字段 F1 柱状图：看 platforms、languages、action_types、target_domains、output_formats 的增减。
- 全量 1000 条覆盖率：哪些字段容易抽出来，哪些字段最吃词表。
- Error analysis：
- 关键字过宽导致 FP。
- 词表覆盖不足导致 FN。
- `gliner_unknown` 大量堆积，说明模型命中后仍卡在归一化层。
- 具体案例：`frontend-design`、`schema-markup-generator`、`manim-composer`、`domain-authority-auditor`。

## 6. 总结与展望
- 主要结论：regex+alias 已经解决了大部分评测样本，GLiNER 当前更多提供补充证据而不是稳定增益。
- 局限：标注集小、1 条缺失样本、词表偏窄、CPU 下模型加载慢。
- 改进方向：扩大受控词表、加入 ChatGPT/Claude/Perplexity 等别名、给 `metrics` 单独做评测、改成 GPU 推理。
