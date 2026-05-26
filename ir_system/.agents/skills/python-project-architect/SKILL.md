---
name: python-project-architect
description: Modularize the Python codebase, define stable CLI/config/state interfaces, and keep the retrieval project maintainable for long-running autonomous work.
license: Proprietary
---

# Python Project Architect

## Use When
- A script has grown too large or mixed responsibilities.
- The project needs stable interfaces for agents, configs, or reports.
- You need to add modules, CLI commands, or state/report files safely.

## Inputs
- `src/skills_ir/`
- `skills_ir_system.py`
- `configs/*.json`
- `runtime/*.json`

## Workflow
1. Separate pure logic, CLI glue, state I/O, and orchestration.
2. Prefer stable JSON files for agent-to-agent handoff.
3. Keep backward compatibility when an existing entrypoint is already in use.
4. Make defaults explicit in config rather than hardcoding behavior in code.
5. Add the minimum structure needed to support future iterations cleanly.

## Outputs
- Clear module boundaries
- Stable CLI and config interfaces
- Agent-readable state/report artifacts

## Done Criteria
- The main entrypoint remains usable.
- Core workflows are testable without editing production data by hand.
- Another engineer or agent can discover the project shape from files alone.
