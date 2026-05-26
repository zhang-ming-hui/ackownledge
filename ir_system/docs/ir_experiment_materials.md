# IR Algorithm Comparison Report

- Generated at: 2026-04-16T04:44:20+00:00
- Eval sets: core_relevance.json
- Top K: 5
- Modes: tfidf, bm25, hybrid

## Aggregate metrics

| Mode | Hit@K | Top1 | MRR@K | Recall@K | Precision@K | Failure Count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| tfidf | 1.0000 | 0.8571 | 0.9107 | 0.9266 | 0.2714 | 9 |
| bm25 | 1.0000 | 0.8333 | 0.8996 | 0.9345 | 0.2762 | 11 |
| hybrid | 1.0000 | 0.8571 | 0.9087 | 0.9345 | 0.2762 | 8 |

## Evaluation-set winners

| Eval set | Best Hit | Best Top1 | Best MRR | Best Recall | Best Precision |
| --- | --- | --- | --- | --- | --- |
| core_relevance.json | tfidf | tfidf | tfidf | bm25 | bm25 |

## Failure samples

### tfidf

- Failure count: 9
- not_top1: query=copywriting for marketing | expected=[copywriting, seo-content-writer] | top=[marketing-skills-collection, marketing-automation, copywriting, seo-schema, content-creation]
- partial_expected_coverage: query=browser automation | expected=[actionbook, agent-browser, browser-use] | top=[agent-browser, browser-automation, browser-use, puppeteer-automation, tdd-workflow]

### bm25

- Failure count: 11
- not_top1: query=copywriting for marketing | expected=[copywriting, seo-content-writer] | top=[marketing-skills-collection, marketing-automation, copywriting, content-creation, seo-fundamentals]
- partial_expected_coverage: query=browser automation | expected=[actionbook, agent-browser, browser-use] | top=[agent-browser, browser-automation, gemini-computer-use, clawdirect-dev, browser-use]

### hybrid

- Failure count: 8
- not_top1: query=copywriting for marketing | expected=[copywriting, seo-content-writer] | top=[marketing-skills-collection, marketing-automation, copywriting, seo-schema, content-creation]
- partial_expected_coverage: query=browser automation | expected=[actionbook, agent-browser, browser-use] | top=[agent-browser, browser-automation, browser-use, puppeteer-automation, gemini-computer-use]

## Innovation notes

- Query-aware hybrid ranking adjusts the BM25 weight by query shape.
- Search results expose tfidf/bm25 components, which keeps ranking explainable.
- Failure buckets make regression analysis reproducible and easy to compare.
