# IR 与 IE 核心逻辑说明

## 1. 文档范围

本项目实际上包含两套核心系统：

- `ir_system`：Information Retrieval，负责“给定一个 query，找出最相关的 skill”
- `ie_system`：Information Extraction，负责“给定一段 skill 描述，抽取出结构化字段”

它们共用同一份数据源 `data/skills_data.json`，但目标不同：

- IR 关注“召回与排序”
- IE 关注“字段识别与证据保留”

---

## 2. `ir_system` 在做什么

### 2.1 核心文件

- `ir_system/src/skills_ir/text.py`：文本规范化、分词、查询扩展
- `ir_system/src/skills_ir/engine.py`：索引构建与检索打分
- `ir_system/src/skills_ir/evaluation.py`：离线评测
- `ir_system/src/skills_ir/comparison.py`：`tfidf` / `bm25` / `hybrid` 比较

### 2.2 IR 核心流程图

```text
共享数据集 data/skills_data.json
            |
            v
按字段读取 skill_name / category / owner / repo / description
            |
            v
分词 + 字段加权
            |
            +--> 建立 TF-IDF 倒排索引
            |
            +--> 建立 BM25 词频/文档长度结构
            |
            v
生成 skills_ir_index.json


用户输入 query
     |
     v
分词 + 查询扩展
     |
     +--> TF-IDF 余弦相似度
     |
     +--> BM25 分数
     |
     v
Hybrid 融合
     |
     v
标题命中 / 描述命中 / phrase_boost / 热度加权
     |
     v
同名 skill 去重
     |
     v
输出最终排序结果
```

### 2.3 IR 的核心逻辑是什么

可以把 IR 理解成两层：

1. 第一层是“统计相关性”
   `engine.py` 同时计算 TF-IDF 和 BM25，让系统既能看“词是否重要”，也能看“词在文档里出现得是否合理”。

2. 第二层是“业务规则修正”
   在基础分上再加标题精确命中、描述覆盖、短语触发、热度信号等 boost，使结果更符合真实使用场景。

### 2.4 IR 例子

假设用户查询：

```text
向量数据库
```

系统会先把 query 扩展成接近下面这种 token 集合：

```text
向量数据库
向量
数据库
vector
database
embedding
qdrant
retrieval
semantic
```

然后检索时可能出现两条候选：

- Skill A：标题中直接包含 `qdrant-vector-search`
- Skill B：描述中提到 `semantic search using embeddings`

此时：

- TF-IDF 会看这些词在文档中的区分度
- BM25 会看这些词的出现频率和文档长度
- Hybrid 会把两者融合
- 如果 Skill A 标题更精确命中，会再拿到额外 boost

所以最后常见结果是：

```text
Skill A 排第 1
Skill B 排第 2
```

也就是说，IR 的本质不是“只看有没有这个词”，而是：

```text
这个 skill 与 query 在语义上像不像
+ 标题是不是直接命中
+ 它是不是一个更可信、更热门的候选
```

---

## 3. `ie_system` 在做什么

### 3.1 核心文件

- `ie_system/src/skills_ie/extractor.py`：规则抽取主流程
- `ie_system/src/skills_ie/evaluation.py`：自动/人工评测
- `ie_system/src/skills_ie/comparison.py`：`baseline` / `enhanced` 变体比较
- `ie_system/src/skills_ie/web.py`：抽取调试与结果浏览

### 3.2 IE 核心流程图

```text
共享数据集 data/skills_data.json
            |
            v
读取 skill_name / category / description / skill_md
            |
            v
选择最完整的抽取文本
            |
            v
规则抽取
  |
  +--> platform 关键字匹配
  +--> language 关键字匹配
  +--> action 关键字匹配
  +--> action alias 扩展
  +--> domain 关键字匹配
  +--> output_format 关键字匹配
  +--> metric 正则匹配
            |
            v
为每个字段记录 evidence
  - rule_source
  - pattern_source
  - matched_text
  - context
            |
            v
生成 event records / extraction report / search view
```

### 3.3 IE 的核心逻辑是什么

IE 不是做自由生成，而是做“可解释的规则抽取”。

它的关键点有两个：

1. 先抽字段值
   例如平台、语言、动作类型、目标领域、输出格式、指标。

2. 再保留证据
   每次命中不只记结果，还会记：
   - 规则来源 `rule_source`
   - 正则或模式 `pattern_source`
   - 命中文本 `matched_text`
   - 上下文 `context`

所以 IE 的真正重点不是“抽出来了没有”，而是：

```text
为什么抽成这个值
这个值是被哪条规则命中的
人工复核时能不能回溯
```

### 3.4 IE 例子

假设某条 skill 描述是：

```text
Build a GitHub workflow that analyzes Python repositories,
generates JSON reports, and tracks SEO content performance
across 5 metrics.
```

IE 可能抽出：

```json
{
  "platforms": ["github"],
  "languages": ["python"],
  "action_types": ["analyze", "generate", "track"],
  "target_domains": ["seo", "content"],
  "output_formats": ["json"],
  "metrics": [
    {
      "value": "5",
      "unit": "metrics"
    }
  ]
}
```

同时保留证据，例如：

```json
{
  "field": "platforms",
  "value": "github",
  "rule_source": "exact_keyword",
  "matched_text": "GitHub",
  "context": "Build a GitHub workflow that analyzes Python repositories"
}
```

这说明：

- `github` 不是模型“猜”的
- 它是被平台关键字规则直接命中的
- 人工可以回到原句验证

---

## 4. IR 和 IE 的关系

这两个系统虽然分开实现，但思路上是互补的。

### 4.1 一个更像“找”

`ir_system` 回答的问题是：

```text
用户想找什么 skill？
哪些候选最相关？
```

### 4.2 一个更像“拆”

`ie_system` 回答的问题是：

```text
这个 skill 具体支持什么平台、语言、动作、输出？
这些字段的证据在哪里？
```

### 4.3 可以这样理解它们的协作

```text
IR 负责从大集合里找候选
IE 负责把候选解释清楚
```

如果未来把两者联动起来，就可以形成一种更完整的体验：

```text
用户 query
  -> IR 返回 Top-K skills
  -> IE 展示每个 skill 的结构化能力标签
  -> 用户更容易判断“为什么推荐它”
```

---

## 5. 两个系统最核心的“可视化理解”

如果只记一句话，可以记成下面两张图。

### 5.1 信息检索 IR

```text
Query
  -> 分词
  -> 查询扩展
  -> TF-IDF / BM25 打分
  -> Hybrid 融合
  -> 规则 boost
  -> 排序 / 去重
  -> Top-K 结果
```

### 5.2 信息抽取 IE

```text
Skill 文本
  -> 关键字规则
  -> 别名规则
  -> 指标正则
  -> 结构化字段
  -> 证据记录
  -> 报告 / 搜索 / 评测
```

---

## 6. 总结

本项目的两套核心逻辑分别是：

- `ir_system`：通过“统计检索 + 规则加权”解决找得准的问题
- `ie_system`：通过“规则抽取 + 证据保留”解决拆得清的问题

如果你从工程视角去看：

- IR 的难点在“召回、排序、评测”
- IE 的难点在“规则覆盖、解释性、字段准确率”

如果你从使用视角去看：

- IR 告诉你“该看哪些 skill”
- IE 告诉你“这些 skill 到底会什么”

后续如果你愿意，我可以继续把这份文档再往前走一步，补成：

1. `ir_system` 的逐函数流程图
2. `ie_system` 的逐函数流程图
3. 一个从 query 到检索结果，再到字段抽取结果的端到端示例

这样你就能直接拿去做实验报告或答辩展示。 
