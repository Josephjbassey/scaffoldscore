# ScaffoldScore leaderboard: bifrost-smoke-MOCK

> **MOCK RUN - EXAMPLE DATA ONLY.** Produced by the deterministic fake LLM (`scaffoldscore/mock_llm.py`). These numbers are not measurements of any real model.


| Agent (scaffold@model) | AgentScore | Success | pass^k | Steps | Tool validity | Injection robust | Capitulation | Discrimination | Tokens/task | Cost/task $ | p50 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|
| plan_execute@openai/mock-large | 93.2 | 91% | 91% | 3.50 | 100% | 84% | 0% | +0 pp | 1,070 | 0.00065 | 8 |
| react@openai/mock-large | 90.3 | 86% | 86% | 2.64 | 100% | 79% | 0% | +0 pp | 626 | 0.00038 | 6 |
| plan_execute@openai/mock-small | 58.2 | 64% | 64% | 3.59 | 86% | 28% | 50% | +7 pp | 1,102 | 0.00006 | 9 |
| react@openai/mock-small | 57.5 | 59% | 59% | 2.64 | 88% | 28% | 46% | +16 pp | 615 | 0.00003 | 6 |
