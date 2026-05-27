# Repository Guidelines

## Project Structure & Module Organization
`ir_system/` contains the retrieval system: `src/skills_ir/` for core code, `configs/` for JSON settings, `eval/` for benchmark sets, `runtime/` for generated indexes and reports, and `docs/` for experiment writeups. `ie_system/` mirrors that layout for information extraction, with generated outputs in `output/` and reports in `runtime/`. `data/` is shared by both systems and holds `skills_data.json`, `skills_data.csv`, checkpoints, and `skill_md/` snapshots. `paqu.py` is the shared crawler/normalizer entry point. Treat `runtime/`, `output/`, and most of `data/skill_md/` as generated artifacts.

## Build, Test, and Development Commands
Use the wrapper scripts at repo root/system root:

- `python ir_system/skills_ir_system.py build-index` builds or reuses `ir_system/runtime/skills_ir_index.json`.
- `python ir_system/skills_ir_system.py search "vector search" --top-k 5` runs IR queries.
- `python ir_system/skills_ir_system.py evaluate --eval-set core_relevance.json` writes retrieval metrics.
- `python ie_system/skills_ie_system.py extract --variant enhanced` generates `ie_system/output/extraction_results.json`.
- `python ie_system/skills_ie_system.py evaluate --eval-set ground_truth.json --variant enhanced` evaluates extraction quality.
- `python paqu.py sync --target-count 500 --headless` refreshes the shared dataset; crawl paths require Selenium and Chrome.
- `python ir_system/skills_ir_system.py serve-web --port 5000` and `python ie_system/skills_ie_system.py serve-web --port 5001` start the local Flask UIs.

## Coding Style & Naming Conventions
Follow the existing Python style: 4-space indentation, type hints, `from __future__ import annotations`, and dataclasses for config objects. Use `snake_case` for modules, functions, CLI flags, and JSON keys; use `PascalCase` for classes such as `SkillsIRSystem` and `SkillsIESystem`. Keep filenames lowercase and descriptive. Preserve UTF-8 when editing Chinese-language configs or docs.

## Testing Guidelines
There is no dedicated `pytest` suite yet; regression testing is CLI-driven. For IR changes, run `build-index`, `evaluate`, and `compare-modes` when ranking logic changes. For IE changes, run `extract`, `evaluate`, and `compare`. If you touch crawling or normalization, validate the shared dataset schema and spot-check generated files before committing.

## Commit & Pull Request Guidelines
Git history is minimal and currently starts with a single initial commit, so keep commit messages short, scoped, and descriptive, for example `ir: tune bm25 weighting` or `ie: tighten action alias regex`. Separate logic changes from bulk regenerated data when possible. PRs should name the affected subsystem, list the commands you ran, mention any regenerated artifacts, and include screenshots for `serve-web` UI changes.
