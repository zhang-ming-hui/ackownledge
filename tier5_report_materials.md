# Tier-5 Report Materials

## 1. Condensed project context

- The project now contains two runnable subsystems:
  - `ir_system`: local information retrieval over the skills dataset.
  - `ie_system`: rule-based information extraction over the same dataset.
- Local dataset scale is `1000` skill documents, which satisfies the course requirement of at least `100` documents.
- Both systems already support automatic evaluation, manual evaluation hooks, and reproducible CLI commands.

## 2. What is already completed

### IR

- Local storage and inverted index construction.
- Vector-space retrieval with TF-IDF and cosine similarity.
- BM25 retrieval and hybrid ranking.
- Natural-language query input and relevance-sorted output.
- Evaluation metrics: `Hit@K`, `Top1`, `MRR@K`, `Recall@K`, `Precision@K`.
- Reproducible mode comparison:
  - `tfidf`
  - `bm25`
  - `hybrid`

### IE

- Extraction of at least six information points:
  - `platforms`
  - `languages`
  - `action_types`
  - `target_domains`
  - `output_formats`
  - `metrics`
- Event-style aggregation per document.
- Regex-based extraction is implemented and remains part of the pipeline.
- Automatic evaluation and baseline-vs-enhanced comparison are both runnable.
- Manual judgment file path is unified.

## 3. Tier-5 innovation points already landed in code

### 3.1 Query-aware hybrid retrieval

- The IR engine does not use a fixed hybrid weight.
- It adjusts the BM25 contribution by query shape, which is a lightweight, explainable approximation of adaptive retrieval.
- This is implemented in:
  - `ir_system/src/skills_ir/engine.py`
  - `ir_system/src/skills_ir/comparison.py`

Why this is a valid innovation for the assignment:

- It is not only a feature; it is an algorithmic change.
- It supports an ablation-style comparison against `tfidf` and `bm25`.
- The score components are exposed, so the ranking remains explainable.

### 3.2 Reproducible IR algorithm comparison

- The project now has a dedicated `compare-modes` command.
- It outputs both JSON and Markdown reports for report writing.
- Generated artifacts:
  - `ir_system/runtime/comparison_report.json`
  - `ir_system/docs/ir_experiment_materials.md`

### 3.3 IE baseline vs enhanced ablation

- The extractor supports:
  - `baseline`
  - `enhanced`
- The enhanced variant adds action-alias expansion rules and improves `action_types`.
- This is implemented in:
  - `ie_system/src/skills_ie/extractor.py`
  - `ie_system/src/skills_ie/cli.py`
  - `ie_system/src/skills_ie/evaluation.py`

### 3.4 Evidence / provenance-oriented extraction

- The IE extractor now preserves field-level evidence.
- Each extracted field can carry:
  - `field`
  - `value`
  - `rule_source`
  - `pattern_source`
  - `matched_text`
  - `context`
- These evidence traces are visible in:
  - `python -m src.skills_ie extract-one ...`
  - `ie_system/output/extraction_results.json`
  - `ie_system/runtime/extraction_report.json`

Why this matters:

- It makes the extractor explainable, not just score-based.
- It supports manual auditing and error analysis.
- It aligns with recent evidence-oriented extraction trends.

## 4. Current experiment results

### IR aggregate metrics on `core_relevance.json`

| Mode | Hit@5 | Top1 | MRR@5 | Recall@5 | Precision@5 | Failures |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| tfidf | 1.0000 | 0.8571 | 0.9107 | 0.9266 | 0.2714 | 9 |
| bm25 | 1.0000 | 0.8333 | 0.8996 | 0.9345 | 0.2762 | 11 |
| hybrid | 1.0000 | 0.8571 | 0.9087 | 0.9345 | 0.2762 | 8 |

Interpretation:

- `tfidf` is currently best on `MRR@5`.
- `hybrid` is stronger on failure count and ties or improves recall/precision.
- Therefore the project should describe hybrid as a more robust and explainable tradeoff, not as a universal winner.

### IE automatic evaluation on `ground_truth.json`

- Enhanced:
  - `Precision = 57.77%`
  - `Recall = 62.50%`
  - `F1 = 60.04%`
- Baseline:
  - `Precision = 54.81%`
  - `Recall = 57.31%`
  - `F1 = 56.04%`
- Delta:
  - `dPrecision = +0.0296`
  - `dRecall = +0.0519`
  - `dF1 = +0.0400`
- Strongest field-level gain:
  - `action_types dF1 = +0.1993`

Explainability summary from the current IE report:

- `total_evidence_items = 7574`
- `action_types` evidence items = `2512`
- Global source distribution:
  - `exact_keyword = 6056`
  - `alias_pattern = 1326`
  - `metric_regex = 192`

## 5. Reproducible commands

### IR

```bash
cd ir_system
python -m src.skills_ir build-index --force
python -m src.skills_ir evaluate
python -m src.skills_ir compare-modes --eval-set core_relevance.json --top-k 5
python -m src.skills_ir review-system --top-k 5
```

### IE

```bash
cd ie_system
python -m src.skills_ie extract --variant enhanced
python -m src.skills_ie extract-one "SEO automation generator with Python that exports JSON and PDF reports across 4 dimensions" --variant enhanced
python -m src.skills_ie evaluate --variant enhanced
python -m src.skills_ie compare --eval-set ground_truth.json
python -m src.skills_ie report --variant enhanced
```

## 6. How to write the Tier-5 section in the final report

Recommended framing:

1. Start from the baseline systems:
   - TF-IDF retrieval
   - regex / dictionary extraction
2. Introduce the two main innovations:
   - query-aware hybrid retrieval
   - evidence-oriented enhanced extraction
3. Show one comparison table for IR and one for IE.
4. Add one short error-analysis subsection:
   - IR: use `failure_buckets.json`
   - IE: use weak fields such as `action_types` and `output_formats`
5. Add one manual-evaluation subsection with 5 to 10 examples.
6. Keep claims precise:
   - say `hybrid is more robust / explainable`
   - do not say `hybrid is strictly best on every metric`

## 7. Literature mapping for the innovation section

These papers were checked on April 16, 2026 and can be cited as recent trend support:

1. Adaptive retrieval by query complexity:
   - Jeong et al., *Adaptive-RAG*, NAACL 2024, June 2024
   - https://aclanthology.org/2024.naacl-long.389/
   - Relevance to this project: motivates query-aware retrieval strategy selection instead of one fixed retrieval mode.

2. Evidence extraction for retrieval pipelines:
   - Zhao et al., *SEER: Self-Aligned Evidence Extraction for Retrieval-Augmented Generation*, EMNLP 2024, November 2024
   - https://aclanthology.org/2024.emnlp-main.178/
   - Relevance to this project: motivates evidence-focused extraction and compact, auditable supporting spans.

3. Grounded and localized document extraction:
   - Perot et al., *LMDX: Language Model-based Document Information Extraction and Localization*, Findings of ACL 2024, August 2024
   - https://aclanthology.org/2024.findings-acl.899/
   - Relevance to this project: motivates preserving grounding or provenance information instead of outputting only final labels.

## 8. Remaining gaps if aiming for an even stronger submission

- IR still needs one more targeted tuning round to make hybrid win more clearly on at least one primary metric set.
- The final written report still needs manual polishing and screenshots/tables.
- Manual evaluation examples should be copied into the final PDF instead of only staying in JSON files.
