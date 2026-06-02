# GLM Extraction Comparison: domain-authority-auditor

- skill_id: bcbc9af8782d
- model: glm-4.5-flash
- shared_text_length: 2821

## Shared Input Preview

```text
Description: Comprehensive domain authority audit across 40 standardized criteria with weighted scoring by domain type. Evaluates domains across 4 dimensions (Citation, Identity, Trust, Eminence) with per-item Pass/Partial/Fail scoring and dimension-specific weights that vary by domain type (Content Publisher, E-commerce, SaaS, etc.) Detects critical manipulation red flags via 3 veto items (link-traffic coherence, backlink uniqueness, penalty history); caps CITE Score at 39 if any veto triggers Produces detailed report with per-item scores, dimension analysis, weighted CITE Score (0-100), and prioritized action plan ranked by impact Pairs with content-quality-auditor for combined 120-item assessment (domain + page-level evaluation) and supports comparative audits across multiple domains

Overview: Domain Authority Auditor Based on CITE Domain Rating . Full benchmark reference: references/cite-domain-rating.md This skill evaluates domain authority across 40 standardized criteria organized in 4 dimensions. It produces a comprehensive audit report with per-item scoring, dimension and weighted scores by domain type, veto item checks, and a prioritized action plan. Sister skill : content-quality-auditor evaluates content at the page level (80 items). This skill evaluates the domain behind the content (40 items). Together they provide a complete 120-item assessment. Namespace note : CITE uses C01-C10 for Citation items; CORE-EEAT uses C01-C10 for Contextual Clarity items. In combined 120-item assessments, prefix with the framework name (e.g., CITE-C01 vs CORE-C01) to avoid confus
```

## baseline

- nonempty_fields: action_types, target_domains, metrics
- info_point_count: 3
- evidence_count: 19
- platforms: []
- languages: []
- action_types: ["audit", "report"]
- target_domains: ["e-commerce", "content"]
- output_formats: []
- metrics: [{"value": "4", "unit": "dimension", "context": "4 dimension", "field": "metrics", "rule_source": "metric_regex", "pattern_source": "(\\d+)[\\-\\s]*(signal|criteria|item|point|step|dimension|layer|level|module|metric|check|rule|test|factor)", "matched_text": "4 dimension"}, {"value": "120", "unit": "item", "context": "120-item", "field": "metrics", "rule_source": "metric_regex", "pattern_source": "(\\d+)[\\-\\s]*(signal|criteria|item|point|step|dimension|layer|level|module|metric|check|rule|test|factor)", "matched_text": "120-item"}, {"value": "80", "unit": "item", "context": "80 item", "field": "metrics", "rule_source": "metric_regex", "pattern_source": "(\\d+)[\\-\\s]*(signal|criteria|item|point|step|dimension|layer|level|module|metric|check|rule|test|factor)", "matched_text": "80 item"}, {"value": "40", "unit": "item", "context": "40 item", "field": "metrics", "rule_source": "metric_regex", "pattern_source": "(\\d+)[\\-\\s]*(signal|criteria|item|point|step|dimension|layer|level|module|metric|check|rule|test|factor)", "matched_text": "40 item"}, {"value": "40", "unit": "standardized", "context": "across 40 standardized", "field": "metrics", "rule_source": "metric_regex", "pattern_source": "(?:across|over|with|covering|spanning)\\s+(\\d+)\\s+([\\w\\-]+)", "matched_text": "across 40 standardized"}, {"value": "4", "unit": "dimensions", "context": "across 4 dimensions", "field": "metrics", "rule_source": "metric_regex", "pattern_source": "(?:across|over|with|covering|spanning)\\s+(\\d+)\\s+([\\w\\-]+)", "matched_text": "across 4 dimensions"}]

## enhanced

- nonempty_fields: action_types, target_domains, metrics
- info_point_count: 3
- evidence_count: 23
- platforms: []
- languages: []
- action_types: ["audit", "report", "analyze", "detect", "evaluate"]
- target_domains: ["e-commerce", "content"]
- output_formats: []
- metrics: [{"value": "4", "unit": "dimension", "context": "4 dimension", "field": "metrics", "rule_source": "metric_regex", "pattern_source": "(\\d+)[\\-\\s]*(signal|criteria|item|point|step|dimension|layer|level|module|metric|check|rule|test|factor)", "matched_text": "4 dimension"}, {"value": "120", "unit": "item", "context": "120-item", "field": "metrics", "rule_source": "metric_regex", "pattern_source": "(\\d+)[\\-\\s]*(signal|criteria|item|point|step|dimension|layer|level|module|metric|check|rule|test|factor)", "matched_text": "120-item"}, {"value": "80", "unit": "item", "context": "80 item", "field": "metrics", "rule_source": "metric_regex", "pattern_source": "(\\d+)[\\-\\s]*(signal|criteria|item|point|step|dimension|layer|level|module|metric|check|rule|test|factor)", "matched_text": "80 item"}, {"value": "40", "unit": "item", "context": "40 item", "field": "metrics", "rule_source": "metric_regex", "pattern_source": "(\\d+)[\\-\\s]*(signal|criteria|item|point|step|dimension|layer|level|module|metric|check|rule|test|factor)", "matched_text": "40 item"}, {"value": "40", "unit": "standardized", "context": "across 40 standardized", "field": "metrics", "rule_source": "metric_regex", "pattern_source": "(?:across|over|with|covering|spanning)\\s+(\\d+)\\s+([\\w\\-]+)", "matched_text": "across 40 standardized"}, {"value": "4", "unit": "dimensions", "context": "across 4 dimensions", "field": "metrics", "rule_source": "metric_regex", "pattern_source": "(?:across|over|with|covering|spanning)\\s+(\\d+)\\s+([\\w\\-]+)", "matched_text": "across 4 dimensions"}]

## project_api_glm

Status: ERROR

project_api_glm: Missing ZHIPUAI_API_KEY environment variable.

## standalone_glm

Status: ERROR

standalone_glm: Missing ZHIPUAI_API_KEY environment variable.
