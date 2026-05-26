---
name: information-retrieval
description: Improve tokenization, query expansion, indexing, and ranking for the skills retrieval engine. Use for search relevance work, ranking experiments, and search debugging.
license: Proprietary
---

# Information Retrieval

## Use When
- A query returns weak results.
- Evaluation misses expected skills or ranks them too low.
- You need to change tokenization, weighting, expansion, or ranking.

## Inputs
- `src/skills_ir/engine.py`
- `src/skills_ir/text.py`
- `configs/ir_config.json`
- `eval/*.json`
- `runtime/failure_buckets.json`

## Workflow
1. Reproduce the failing query.
2. Identify the cause:
   - tokenization gap
   - missing expansion
   - field weighting issue
   - popularity boost overpowering relevance
   - missing data
3. Prefer the smallest change that improves the failing bucket without harming nearby queries.
4. Re-run the relevant evaluation set and compare metrics.
5. Record what changed and which failure bucket it targets.

## Outputs
- Retrieval code or config changes
- Before/after evaluation evidence
- A clear explanation of why the change improved relevance

## Done Criteria
- The targeted failure bucket improves.
- No baseline evaluation regression is introduced without explicit justification.
- Changes remain configurable where practical.
