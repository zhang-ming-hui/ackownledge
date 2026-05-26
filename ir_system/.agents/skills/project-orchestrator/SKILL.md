---
name: project-orchestrator
description: Coordinate long-running autonomous work on the skills retrieval project. Use when the task is to decide the next iteration, assign work to retrieval/data/evaluation agents, or produce a cycle summary.
license: Proprietary
---

# Project Orchestrator

## Use When
- The goal is to move the retrieval project forward over multiple iterations.
- You need to choose the next high-value task from metrics, failure buckets, or stale data.
- You need to summarize project state for another agent.

## Inputs
- `runtime/project_state.json`
- `runtime/cycle_report.json`
- `runtime/metrics_report.json`
- `runtime/failure_buckets.json`
- `configs/agent_config.json`

## Workflow
1. Read the latest project state and cycle report.
2. Check whether the dataset is stale or missing.
3. Check whether evaluation has failures and which bucket is largest.
4. Choose the next task in this order:
   - Restore broken pipeline
   - Fix largest failure bucket
   - Expand stale or weak evaluation coverage
   - Expand dataset
   - Refactor for maintainability
5. Produce a short iteration brief with owner, goal, and acceptance criteria.

## Outputs
- A concrete next task for one agent
- Updated priorities for the next cycle
- A concise cycle summary that references actual metrics

## Done Criteria
- The next task is unambiguous.
- The task has an owner, a measurable goal, and a validation step.
- Recommendations are grounded in repo state, not guesses.
