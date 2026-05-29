# IE Evaluation Diagnostic Report

- Generated at: 2026-05-29T09:09:28+00:00
- Primary eval set: ground_truth_expanded.json
- Secondary eval set: ground_truth.json
- Full GLiNER source: cached_extraction_results

## ground_truth_expanded.json

- Samples: 24
- Field support: {'platforms': 8, 'languages': 9, 'action_types': 22, 'target_domains': 16, 'output_formats': 11}

| Variant | Macro P | Macro R | Macro F1 | Micro P | Micro R | Micro F1 | Matched docs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 0.3329 | 0.5024 | 0.4005 | 0.2746 | 0.6974 | 0.3941 | 24 |
| enhanced_regex | 0.6937 | 0.7845 | 0.7363 | 0.6485 | 0.8618 | 0.7401 | 24 |
| enhanced_gliner | 0.7046 | 0.8083 | 0.7529 | 0.6473 | 0.8816 | 0.7465 | 24 |

- Regex -> GLiNER changed 4 skills / 4 skill-field pairs.
- Gain field-cases: 3, hurt field-cases: 1, same field-cases: 116.

## ground_truth.json

- Samples: 10
- Field support: {'platforms': 4, 'languages': 3, 'action_types': 10, 'target_domains': 8, 'output_formats': 4}

| Variant | Macro P | Macro R | Macro F1 | Micro P | Micro R | Micro F1 | Matched docs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 0.3321 | 0.4348 | 0.3766 | 0.2647 | 0.5070 | 0.3478 | 9 |
| enhanced_regex | 0.5823 | 0.6102 | 0.5959 | 0.5610 | 0.6479 | 0.6013 | 9 |
| enhanced_gliner | 0.5712 | 0.6102 | 0.5900 | 0.5595 | 0.6620 | 0.6065 | 9 |

- Regex -> GLiNER changed 2 skills / 2 skill-field pairs.
- Gain field-cases: 1, hurt field-cases: 0, same field-cases: 44.

## Full Dataset Regex vs GLiNER

- Skipped: full compare disabled

## GLiNER Unknowns

- Total gliner_unknown evidence items: 4108
- Field counts: {'target_domains': 16, 'platforms': 1819, 'output_formats': 468, 'languages': 1393, 'action_types': 412}

| Reason | Count |
| --- | ---: |
| other_platform_unknown | 1709 |
| other_language_unknown | 1211 |
| other_output_unknown | 445 |
| other_action_unknown | 393 |
| cross_field_confusion | 104 |
| tool_or_model_name | 103 |
| vocab_missing_platform | 50 |
| vocab_missing_language_or_framework | 35 |
| vocab_missing_target_domain | 16 |
| generic_or_meta_span | 14 |
| action_noun_needs_alias_or_filter | 13 |
| vocab_missing_output_format | 9 |
| protocol_token | 6 |

### Recommended Vocabulary / Alias Fixes

| Field | Value | Count | Suggested action |
| --- | --- | ---: | --- |
| platforms | ccc | 15 | consider extending controlled vocabulary |
| languages | git | 12 | consider extending controlled vocabulary |
| platforms | tzst | 12 | consider extending controlled vocabulary |
| platforms | Base | 10 | consider extending controlled vocabulary |
| languages | npm | 10 | consider extending controlled vocabulary |
| platforms | dmux | 10 | consider extending controlled vocabulary |
| languages | BigQuery | 9 | consider extending controlled vocabulary |
| target_domains | Industry | 4 | consider extending controlled vocabulary |
| target_domains | industry | 4 | consider extending controlled vocabulary |
| languages | Git | 4 | consider extending controlled vocabulary |
| output_formats | OG images | 3 | consider extending controlled vocabulary |
| output_formats | music | 3 | consider extending controlled vocabulary |
| output_formats | images | 3 | consider extending controlled vocabulary |
| platforms | base | 3 | consider extending controlled vocabulary |
| target_domains | SaaS | 1 | consider extending controlled vocabulary |
