# Bifrost verification log (15 Nov 2026)

No LLM API keys were used. The goal was to prove that ScaffoldScore talks to Bifrost over its
OpenAI-compatible API and that Bifrost logs every agent call. The upstream "provider" was the
fake LLM served by `scaffoldscore mock-server`, so all numbers here are **mock / example data**.

## 1. Bifrost starts

`npx -y @maximhq/bifrost -port 8080 -app-dir ./bifrost-data` downloaded Bifrost **v2.5.1** and logged
`successfully started bifrost, serving UI on http://localhost:8080/`. `GET /health` returned
`{"components":{"db_pings":"ok"},"status":"ok"}`.

## 2. Routing to an OpenAI-compatible upstream

Config: [`bifrost-config.mock.json`](bifrost-config.mock.json) registers the `openai` provider with
`base_url` `http://127.0.0.1:9100` (the fake LLM) and a placeholder key. Notes for v2.5.x:
- a key's `models` must be `["*"]` (an empty list denies all models);
- with a config file, inference auth is on unless `client.enforce_auth_on_inference` is `false`;
  otherwise send a virtual key in the `x-bf-vk` header (`BIFROST_VIRTUAL_KEY` in ScaffoldScore).

Direct request through Bifrost:

```
POST http://localhost:8080/v1/chat/completions  {"model": "openai/mock-large", ...}
-> {"choices":[{"message":{"role":"assistant","content":"FINAL ANSWER: Abuja"}}],
    "usage":{"prompt_tokens":13,"completion_tokens":4,"total_tokens":17},
    "extra_fields":{"routing_info":{"provider":"openai","model":"mock-large","key":"mock-key"}, "latency":1, ...}}
```

## 3. Full harness run through Bifrost

`scaffoldscore run --config configs/bifrost-mock.yaml` (2 fake models × 2 scaffolds × 22 tasks, with
pushback and injection) finished 168 episodes in about 1.4 s. Bifrost's request log
(`bifrost-data/logs.db`, table `logs`) gained **616 rows** for that run, split between `mock-large`
and `mock-small`, each with token counts and latency. Results: `results/bifrost-smoke-MOCK/`
(labelled MOCK).

Bifrost's `/api/logs` and dashboard need an admin account or a setup token in v2.5.x; on your machine,
finish the onboarding in the UI at http://localhost:8080 to browse the same logs there.
