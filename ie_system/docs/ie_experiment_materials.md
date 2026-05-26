# IE variant comparison report

- Generated at: 2026-04-16T04:50:29+00:00
- Eval file: ground_truth.json

## Overall metrics

| Variant | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| baseline | 0.5481 | 0.5731 | 0.5604 |
| enhanced | 0.5777 | 0.6250 | 0.6004 |

## Coverage summary

| Variant | Total docs | Docs with >=5 points | Docs with no extraction |
| --- | ---: | ---: | ---: |
| baseline | 1000 | 55 | 132 |
| enhanced | 1000 | 84 | 116 |

## Explainability summary

| Variant | Field | Docs with evidence | Coverage | Evidence items | Top source |
| --- | --- | ---: | ---: | ---: | --- |
| baseline | platforms | 187 | 0.1870 | 597 | exact_keyword |
| baseline | languages | 358 | 0.3580 | 1119 | exact_keyword |
| baseline | action_types | 468 | 0.4680 | 1186 | exact_keyword |
| baseline | target_domains | 778 | 0.7780 | 2375 | exact_keyword |
| baseline | output_formats | 363 | 0.3630 | 779 | exact_keyword |
| baseline | metrics | 163 | 0.1630 | 192 | metric_regex |
| enhanced | platforms | 187 | 0.1870 | 597 | exact_keyword |
| enhanced | languages | 358 | 0.3580 | 1119 | exact_keyword |
| enhanced | action_types | 713 | 0.7130 | 2512 | alias_pattern |
| enhanced | target_domains | 778 | 0.7780 | 2375 | exact_keyword |
| enhanced | output_formats | 363 | 0.3630 | 779 | exact_keyword |
| enhanced | metrics | 163 | 0.1630 | 192 | metric_regex |

## Field deltas

| Field | Precision delta | Recall delta | F1 delta |
| --- | ---: | ---: | ---: |
| platforms | +0.0000 | +0.0000 | +0.0000 |
| languages | +0.0000 | +0.0000 | +0.0000 |
| action_types | +0.1481 | +0.2593 | +0.1993 |
| target_domains | +0.0000 | +0.0000 | +0.0000 |
| output_formats | +0.0000 | +0.0000 | +0.0000 |

## Innovation notes

- Baseline keeps exact keyword matching only.
- Enhanced adds action alias expansion for better recall on semantically similar text.
- Field-level delta tables make the improvement easy to explain in the report.
