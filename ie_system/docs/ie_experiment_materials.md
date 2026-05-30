# IE variant comparison report

- Generated at: 2026-05-30T05:20:32+00:00
- Eval file: ground_truth_expanded.json

## Overall metrics

| Variant | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| baseline | 0.3329 | 0.5024 | 0.4005 |
| enhanced | 0.6937 | 0.7845 | 0.7363 |

## Coverage summary

| Variant | Total docs | Docs with >=5 points | Docs with no extraction |
| --- | ---: | ---: | ---: |
| baseline | 1000 | 339 | 9 |
| enhanced | 1000 | 106 | 8 |

## Explainability summary

| Variant | Field | Docs with evidence | Coverage | Evidence items | Top source |
| --- | --- | ---: | ---: | ---: | --- |
| baseline | platforms | 416 | 0.4160 | 3222 | exact_keyword |
| baseline | languages | 659 | 0.6590 | 7975 | exact_keyword |
| baseline | action_types | 906 | 0.9060 | 14713 | exact_keyword |
| baseline | target_domains | 962 | 0.9620 | 13756 | exact_keyword |
| baseline | output_formats | 737 | 0.7370 | 9378 | exact_keyword |
| baseline | metrics | 177 | 0.1770 | 276 | metric_regex |
| enhanced | platforms | 235 | 0.2350 | 760 | keyword_fallback |
| enhanced | languages | 424 | 0.4240 | 1440 | keyword_fallback |
| enhanced | action_types | 907 | 0.9070 | 4005 | alias_fallback |
| enhanced | target_domains | 927 | 0.9270 | 3067 | keyword_fallback |
| enhanced | output_formats | 470 | 0.4700 | 1286 | keyword_fallback |
| enhanced | metrics | 177 | 0.1770 | 276 | metric_regex |

## Field deltas

| Field | Precision delta | Recall delta | F1 delta |
| --- | ---: | ---: | ---: |
| platforms | +0.4615 | +0.5308 | +0.4985 |
| languages | +0.5296 | +0.4556 | +0.4960 |
| action_types | +0.3859 | +0.2853 | +0.3769 |
| target_domains | +0.1330 | +0.0091 | +0.1121 |
| output_formats | +0.2939 | +0.1297 | +0.2495 |

## Innovation notes

- Baseline keeps exact keyword matching only.
- Enhanced adds action alias expansion for better recall on semantically similar text.
- Field-level delta tables make the improvement easy to explain in the report.
