"""Minimal OpenAI-compatible chat client (stdlib only).

Point it at Bifrost (http://localhost:8080/v1) so every agent call goes through
one gateway: Bifrost picks the provider from the model prefix (groq/..., gemini/...,
openrouter/..., ollama/...), and logs tokens, latency and cost per request.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field


@dataclass
class ChatResult:
    content: str = ""
    tool_calls: list = field(default_factory=list)  # [{id, name, arguments(str)}]
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None  # filled when the gateway reports it
    latency_ms: float = 0.0
    error: str | None = None
    raw: dict | None = None


def _extract_cost(resp: dict):
    for holder in (resp.get("usage") or {}, resp.get("extra_fields") or {}):
        c = holder.get("cost")
        if isinstance(c, (int, float)):
            return float(c)
        if isinstance(c, dict):
            for k in ("total_cost", "total"):
                if isinstance(c.get(k), (int, float)):
                    return float(c[k])
    return None


class OpenAICompatClient:
    def __init__(self, base_url: str, api_key: str | None = None, timeout: float = 120,
                 retries: int = 3, extra_headers: dict | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.retries = retries
        self.extra_headers = extra_headers or {}

    def _post(self, path: str, payload: dict) -> dict:
        headers = {"Content-Type": "application/json", **self.extra_headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.base_url + path, data=json.dumps(payload).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    def list_models(self) -> list[str]:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        req = urllib.request.Request(self.base_url + "/models", headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            return [m.get("id") for m in json.load(r).get("data", [])]

    def chat(self, model, messages, tools=None, temperature=0.0, max_tokens=512, seed=None) -> ChatResult:
        payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if seed is not None:
            payload["seed"] = seed
        last_err = None
        for attempt in range(self.retries):
            t0 = time.perf_counter()
            try:
                resp = self._post("/chat/completions", payload)
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")[:500]
                last_err = f"HTTP {e.code}: {body}"
                if e.code in (429, 500, 502, 503, 504) and attempt < self.retries - 1:
                    time.sleep(2 ** attempt * 2)
                    continue
                return ChatResult(error=last_err, latency_ms=(time.perf_counter() - t0) * 1000)
            except Exception as e:  # network error, timeout
                last_err = f"{type(e).__name__}: {e}"
                if attempt < self.retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return ChatResult(error=last_err, latency_ms=(time.perf_counter() - t0) * 1000)
            latency = (time.perf_counter() - t0) * 1000
            if "choices" not in resp:
                return ChatResult(error=f"bad response: {json.dumps(resp)[:500]}", latency_ms=latency)
            msg = resp["choices"][0].get("message") or {}
            calls = []
            for tc in msg.get("tool_calls") or []:
                fn = tc.get("function") or {}
                args = fn.get("arguments", "")
                calls.append({"id": tc.get("id") or f"call_{len(calls)}", "name": fn.get("name", ""),
                              "arguments": args if isinstance(args, str) else json.dumps(args)})
            usage = resp.get("usage") or {}
            return ChatResult(content=msg.get("content") or "", tool_calls=calls,
                              prompt_tokens=int(usage.get("prompt_tokens") or 0),
                              completion_tokens=int(usage.get("completion_tokens") or 0),
                              cost_usd=_extract_cost(resp), latency_ms=latency, raw=resp)
        return ChatResult(error=last_err)
