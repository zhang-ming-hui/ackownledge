---
name: project-completion-reviewer
description: Run the retrieval project, inspect metrics and failure buckets, and decide whether the system is ready for the next product step such as a web UI.
license: Proprietary
---

# Project Completion Reviewer

## Use When
- Code has changed and the project needs a completion review.
- You need to decide whether the current baseline is strong enough for productization.
- You need to identify unreasonable factors after running the system.

## Inputs
- `skills_ir_system.py`
- `src/skills_ir/`
- `eval/*.json`
- `runtime/*.json`

## Workflow
1. Run the available non-destructive checks:
   - CLI search
   - evaluation
   - run-cycle
   - report inspection
2. Confirm whether runtime artifacts are generated correctly.
3. Review failure buckets and separate:
   - acceptable known relevance gaps
   - blocking functional gaps
   - productization gaps
4. Decide whether the project is ready for the next phase, such as a minimal web UI.

## Outputs
- A concise completed vs missing checklist
- A short list of blockers
- A readiness decision for the next product step

## Done Criteria
- The review is based on executed checks, not assumptions.
- Missing work is prioritized by user impact.
- The recommendation is actionable for the next agent.
