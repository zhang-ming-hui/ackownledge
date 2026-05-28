# IE variant comparison report

- Generated at: 2026-05-28T06:41:41+00:00
- Eval file: ground_truth.json

## Overall metrics

| Variant | Precision | Recall | F1 |
| --- | ---: | ---: | ---: |
| baseline | 0.3321 | 0.4348 | 0.3766 |
| enhanced | 0.5971 | 0.6102 | 0.6036 |

## Coverage summary

| Variant | Total docs | Docs with >=5 points | Docs with no extraction |
| --- | ---: | ---: | ---: |
| baseline | 1000 | 339 | 9 |
| enhanced | 1000 | 103 | 10 |

## Explainability summary

| Variant | Field | Docs with evidence | Coverage | Evidence items | Top source |
| --- | --- | ---: | ---: | ---: | --- |
| baseline | platforms | 416 | 0.4160 | 3222 | exact_keyword |
| baseline | languages | 659 | 0.6590 | 7975 | exact_keyword |
| baseline | action_types | 906 | 0.9060 | 14713 | exact_keyword |
| baseline | target_domains | 962 | 0.9620 | 13756 | exact_keyword |
| baseline | output_formats | 735 | 0.7350 | 9050 | exact_keyword |
| baseline | metrics | 177 | 0.1770 | 276 | metric_regex |
| enhanced | platforms | 235 | 0.2350 | 760 | keyword_fallback |
| enhanced | languages | 424 | 0.4240 | 1440 | keyword_fallback |
| enhanced | action_types | 872 | 0.8720 | 3737 | alias_fallback |
| enhanced | target_domains | 927 | 0.9270 | 3067 | keyword_fallback |
| enhanced | output_formats | 464 | 0.4640 | 1258 | keyword_fallback |
| enhanced | metrics | 177 | 0.1770 | 276 | metric_regex |

## Field deltas

| Field | Precision delta | Recall delta | F1 delta |
| --- | ---: | ---: | ---: |
| platforms | +0.5000 | +0.6500 | +0.5882 |
| languages | +0.2262 | +0.2083 | +0.2171 |
| action_types | +0.2714 | +0.1111 | +0.2109 |
| target_domains | +0.2218 | -0.0926 | +0.1217 |
| output_formats | +0.1056 | +0.0000 | +0.0758 |

## Innovation notes

- Baseline keeps exact keyword matching only.
- Enhanced adds action alias expansion for better recall on semantically similar text.
- Field-level delta tables make the improvement easy to explain in the report.
