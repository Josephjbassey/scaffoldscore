"""Serve the deterministic fake LLM as an OpenAI-compatible /v1/chat/completions endpoint.

Used to prove the gateway path end-to-end without any API key:
  scaffoldscore -> Bifrost (localhost:8080) -> this server (localhost:9100).
Responses are scripted EXAMPLE DATA, not a model."""
from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .mock_llm import MockLLM
from .runner import ROOT
from .tasks import load_tasks

LLM = MockLLM(load_tasks([ROOT / "tasks" / "core.yaml", ROOT / "tasks" / "live_tavily.yaml"]))
MODELS = ["mock-large", "mock-small", "mock-sycophant"]


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._send(200, {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "mock"} for m in MODELS]})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._send(404, {"error": "not found"})
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        model = req.get("model", "mock-large").replace("mock-", "")
        r = LLM.chat(model, req["messages"], tools=req.get("tools"), seed=req.get("seed"))
        msg = {"role": "assistant", "content": r.content or None}
        if r.tool_calls:
            msg["tool_calls"] = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}} for c in r.tool_calls]
        self._send(200, {"id": f"mock-{time.time_ns()}", "object": "chat.completion", "created": int(time.time()),
                         "model": req.get("model"), "choices": [{"index": 0, "message": msg,
                         "finish_reason": "tool_calls" if r.tool_calls else "stop"}],
                         "usage": {"prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens,
                                   "total_tokens": r.prompt_tokens + r.completion_tokens}})


def serve(port=9100):
    print(f"[mock-server] fake OpenAI-compatible LLM on http://127.0.0.1:{port}/v1 (EXAMPLE DATA ONLY)")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
