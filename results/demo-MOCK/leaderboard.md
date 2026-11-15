# ScaffoldScore leaderboard: demo-MOCK

> **MOCK RUN - EXAMPLE DATA ONLY.** Produced by the deterministic fake LLM (`scaffoldscore/mock_llm.py`). These numbers are not measurements of any real model.


| Agent (scaffold@model) | AgentScore | Success | pass^k | Steps | Tool validity | Injection robust | Capitulation | Discrimination | Tokens/task | Cost/task $ | p50 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| react_verify@mock/large | 96.3 | 95% | 95% | 3.50 | 99% | 95% | 3% | n/a | 901 | 0.00055 | 3,132 |
| plan_execute@mock/large | 93.7 | 94% | 91% | 3.50 | 99% | 88% | 3% | -3 pp | 1,070 | 0.00065 | 3,216 |
| react@mock/large | 92.1 | 92% | 86% | 2.64 | 99% | 86% | 3% | -3 pp | 625 | 0.00038 | 2,112 |
| plan_execute@mock/sycophant | 70.7 | 92% | 86% | 3.52 | 97% | 60% | 82% | +18 pp | 1,081 | 0.00022 | 1,801 |
| react_verify@mock/sycophant | 66.4 | 85% | 64% | 3.45 | 97% | 68% | 82% | +4 pp | 888 | 0.00018 | 1,738 |
| react_verify@mock/small | 66.4 | 77% | 64% | 3.48 | 86% | 38% | 33% | +44 pp | 903 | 0.00005 | 1,032 |
| plan_execute@mock/small | 62.4 | 79% | 59% | 3.55 | 85% | 25% | 37% | +30 pp | 1,094 | 0.00006 | 1,076 |
| react@mock/sycophant | 61.9 | 82% | 59% | 2.59 | 97% | 53% | 81% | +7 pp | 614 | 0.00013 | 1,182 |
| react@mock/small | 60.8 | 74% | 55% | 2.61 | 86% | 24% | 35% | +32 pp | 621 | 0.00003 | 704 |
| single_shot@mock/large | 41.4 | 15% | 9% | 1.00 | n/a | n/a | 0% | +4 pp | 80 | 0.00005 | 1,056 |
| single_shot@mock/small | 29.9 | 24% | 9% | 1.00 | n/a | n/a | 44% | -2 pp | 79 | 0.00000 | 352 |
| single_shot@mock/sycophant | 6.6 | 11% | 9% | 1.00 | n/a | n/a | 100% | -22 pp | 80 | 0.00002 | 591 |
