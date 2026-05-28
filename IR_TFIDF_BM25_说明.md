# IR 系统 TF-IDF 与 BM25 说明

## 概述

IR 系统的检索引擎（`ir_system/src/skills_ir/engine.py` 中的 `SkillsIRSystem`）采用 **TF-IDF + BM25 混合检索**。两个算法共用一套倒排索引结构，在搜索时融合两者的分数得到最终排序结果。

---

## 1. 两个结构的作用

| 结构 | 对应字段 | 作用 |
|------|---------|------|
| **TF-IDF 倒排索引** | `postings`, `idf`, `doc_norms` | 将每个文档映射为向量，查询时做**余弦相似度**匹配，衡量"查询和文档在语义向量空间中的方向一致性" |
| **BM25 结构** | `bm25_idf`, `bm25_tf`, `doc_lengths`, `avg_doc_length` | 基于**概率检索模型**，综合词频、文档长度归一化、逆文档频率来计算相关性分，衡量"查询词在文档中的重要性" |

检索时采用**混合模式 (hybrid)**，两者共同参与打分：

```
final_score = (1 - bm25_weight) × cosine + bm25_weight × bm25_norm
```

- TF-IDF 余弦相似度占主导：中文查询 98%，英文查询 86%~92%
- BM25 作为补充：中文查询 2%，英文查询 8%~14%（token 越多，BM25 权重越高）

---

## 2. TF-IDF 倒排索引

### 构建阶段

1. **字段加权分词**：每个文档的 `skill_name`、`description`、`category` 等字段按 `config.field_weights` 配置的权重进行 term 提取，权重高的字段中 term 计数倍增。

2. **计算 IDF**（逆文档频率）：
   ```
   idf[term] = ln((总文档数 + 1) / (出现该 term 的文档数 + 1)) + 1.0
   ```
   平滑版 IDF，避免除零，IDF 恒 ≥ 1.0。

3. **构建倒排索引**（postings）：
   ```
   tf_weight = (1.0 + ln(tf)) × idf[term]
   postings[term][doc_id] = tf_weight
   ```
   用 sublinear TF 缩放（`1+ln(tf)`）抑制高频词；同时计算各文档向量的 L2 范数存入 `doc_norms`。

### 查询阶段

1. 查询同样按 `(1+ln(tf)) × idf` 构建查询向量。
2. 在 `postings` 中做稀疏累加——只遍历查询 term 命中的倒排链，不遍历全部文档。
3. 用余弦相似度归一化：
   ```
   cosine = (query_vec · doc_vec) / (|query_vec| × |doc_vec|)
   ```

---

## 3. BM25 词频/文档长度结构

### 构建阶段

1. **BM25 专用 IDF**：
   ```
   bm25_idf[term] = ln((总文档数 - 出现文档数 + 0.5) / (出现文档数 + 0.5) + 1.0)
   ```
   这是 BM25 的 Robertson-Spärck Jones 权重，与 TF-IDF 的 IDF 公式不同，对高频词和低频词的区分更平滑。

2. **原始词频**：`bm25_tf[term][doc_id]` 保存原始 tf 值（不做对数压缩）。

3. **文档长度**：
   - `doc_lengths[doc_id]` = 每个文档的总词数
   - `avg_doc_length` = 所有文档的平均长度

### 查询阶段

BM25 标准公式，参数 `k1=1.5`, `b=0.75`：

```
                          tf × (k1 + 1)
BM25(doc, query) = Σ idf(term) × ─────────────────────────────
                   term∈query     tf + k1 × (1 - b + b × dl/avgdl)
```

- **k1 = 1.5**：控制词频饱和速度。词频再高也不会无限贡献分数。
- **b = 0.75**：控制文档长度归一化强度。b 越大，长文档被惩罚越多。
- **dl/avgdl**：文档长度比，长文档中的词频贡献被适当稀释。

---

## 4. 混合融合与规则加权

在混合分数基础上，`_apply_boosts()` 方法叠加以下规则性提升：

- **标题精确匹配**：+0.25
- **描述精确匹配**：+0.12
- **分类命中**：每个词 +0.05
- **标题 token 命中**：每个 token +0.12（上限 0.36）
- **描述 token 命中**：每个 token +0.02（上限 0.12）
- **查询覆盖率**：按命中 token 比例，最高 +0.30
- **短语触发 Boost**：配置中的 `phrase_boosts` 规则
- **热度加权**：`ln(1+installs)×0.006 + ln(1+stars)×0.005`

---

## 5. 索引文件结构

`ir_system/runtime/skills_ir_index.json` 的顶层字段：

```json
{
  "index_version": 3,
  "source_record_count": 1000,
  "documents": [
    // 1000 个原始技能文档
  ],
  "postings": {
    // 15466 个 term → {doc_id: tfidf_weight}
    // TF-IDF 倒排索引
  },
  "idf": {
    // 15466 个 term → idf_value
    // TF-IDF 的 IDF
  },
  "doc_norms": {
    // 1000 个 doc_id → L2 范数
  },
  "bm25_idf": {
    // 15466 个 term → bm25_idf_value
    // BM25 专用 IDF
  },
  "bm25_tf": {
    // 15466 个 term → {doc_id: raw_tf}
    // BM25 原始词频
  },
  "doc_lengths": {
    // 1000 个 doc_id → 文档总词数
  },
  "avg_doc_length": 327.097
}
```

所有 TF-IDF 和 BM25 数据均在索引文件中，`postings`、`idf`、`doc_norms` 属于 TF-IDF 部分，`bm25_idf`、`bm25_tf`、`doc_lengths`、`avg_doc_length` 属于 BM25 部分。
