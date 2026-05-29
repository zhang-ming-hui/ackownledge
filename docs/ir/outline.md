# IR 实验报告提纲

## 1. 引言
- 技能检索问题定义：面向 skills.sh 技能库的离线语义检索，不做通用网页搜索。
- 应用场景：按任务需求找技能、处理中英混合查询、解释排名原因。
- 数据集概况：1000 条 skill 记录，主字段 + 外置 `SKILL.md` 文本。
- 实验目标：验证 TF-IDF、BM25、混合检索和后置 boost 的效果差异。

## 2. 数据获取与预处理
- `paqu.py` 抓取流程：滚动收集 URL -> 详情页解析 -> `SKILL.md` 提取 -> 规范化 -> checkpoint 落盘。
- 数据字段表：`skill_name`、`description`、`category`、`repo_url`、`weekly_installs_num`、`github_stars_num`、`skill_md_text_path`。
- 数据质量统计：1000 条记录、917 条带 `SKILL.md`、203 条缺 description。
- 文本预处理：空白规整、英文 token 变体拆分、中文整段/单字/双字切分、查询扩展。

## 3. 核心算法
- 文档加权：字段加权词频、TF-IDF 权重、余弦相似度公式。
- BM25：完整公式、`k1=1.5`、`b=0.75`、文档长度归一化。
- 混合融合：`score=(1-\alpha)cosine+\alpha BM25_norm`，`alpha` 按中英混合和 query 长度动态取值。
- 后置 boost：标题精确匹配、description 命中、category 命中、token 覆盖率、短查询标题直击、热度修正。
- 倒排索引结构表：`postings`、`idf`、`doc_norms`、`bm25_tf`、`doc_lengths`、`avg_doc_length`。
- 伪代码：检索主流程。

## 4. 实验设计与过程
- 实验环境：Windows 10，conda `yolov82`，Python 3.11.5，XeTeX Live 2024。
- 评测集：`core_relevance.json`，42 条查询，`top_k=5`。
- 指标：代码内已有 Hit@K / Top1 / MRR / Recall / Precision；补充计算 `nDCG@5`。
- 命令与输出：`build-index`、`evaluate`、`compare-modes`、输出到 `ir_system/runtime/`。

## 5. 实验结果与分析
- 模式对比表：TF-IDF / BM25 / hybrid 的 `P@5`、`nDCG@5`、`MRR@5`。
- `alpha` 扫描图：固定 BM25 权重对 `P@5` 和 `nDCG@5` 的影响。
- 中文 / 英文 / mixed 查询分析：动态 `alpha` 差异和效果差异。
- 失败案例：`copywriting for marketing`、`browser automation`、`SEO audit`、`SQL queries`。

## 6. 总结与展望
- 主要结论：当前数据上 TF-IDF 仍是主力，BM25 适合轻量补充。
- 局限：中文文档占比很低、查询扩展规则较手工、没有学习排序。
- 改进方向：扩大中文词表、引入 dense reranker、把 `nDCG` 纳入正式评测。
