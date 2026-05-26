---
name: dataset-cleaning
description: Clean, normalize, deduplicate, and validate scraped skill records before indexing. Use when improving crawl output quality or repairing inconsistent records.
license: Proprietary
---

# Dataset Cleaning

## Use When
- Crawl output has duplicates, malformed fields, or missing normalized values.
- Retrieval failures are caused by bad or inconsistent source records.
- The project needs safer checkpoint or normalization logic.

## Inputs
- `paqu.py`
- `skills_checkpoint.json`
- `skills_data_500.json`
- `skills_data_500.csv`

## Workflow
1. Inspect record quality and identify repeatable normalization rules.
2. Prefer deterministic cleanup over ad hoc manual edits.
3. Keep raw meaning intact while normalizing formats.
4. Preserve stable identifiers and URLs whenever possible.
5. Validate that cleaned output still supports indexing and evaluation.

## Outputs
- Safer crawl/cleaning logic
- Cleaner dataset fields
- Notes about changed normalization assumptions

## Done Criteria
- Duplicate or malformed records are reduced.
- Record shape remains index-compatible.
- Changes are explainable and repeatable.
