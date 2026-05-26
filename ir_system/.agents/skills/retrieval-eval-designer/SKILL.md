---
name: retrieval-eval-designer
description: Maintain evaluation datasets, failure buckets, and relevance metrics for the skills retrieval project. Use when adding benchmark queries, categorizing failures, or defining acceptance criteria.
license: Proprietary
---

# Retrieval Eval Designer

## Use When
- Evaluation coverage is too small.
- A new feature needs acceptance criteria.
- You need to group retrieval failures into actionable buckets.

## Inputs
- `eval/*.json`
- `runtime/metrics_report.json`
- `runtime/failure_buckets.json`
- `configs/ir_config.json`

## Workflow
1. Review existing evaluation gaps by query type and failure bucket.
2. Add queries that are realistic, compact, and tied to known skill targets.
3. Label each case with `query_type`.
4. Keep expected skill names grounded in the current dataset.
5. When failures exist, cluster them by likely root cause rather than surface symptoms only.

## Outputs
- Expanded evaluation cases
- Query-type coverage improvements
- Actionable failure buckets

## Done Criteria
- New eval cases are reproducible and reference existing skills.
- Metrics can be compared before and after changes.
- Failure buckets help another agent choose the next task.
