"""Sandboxed, deterministic tools. Nothing here touches the network except the
optional Tavily tool, which is only active when TAVILY_API_KEY is set."""
from __future__ import annotations

import ast
import copy
import json
import math
import operator
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# ---------------------------------------------------------------- calculator
_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
        ast.FloorDiv: operator.floordiv}
_UN = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"sqrt": math.sqrt, "round": round, "abs": abs, "min": min, "max": max,
          "floor": math.floor, "ceil": math.ceil, "log": math.log, "exp": math.exp}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("exponent too large")
        return _BIN[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UN:
        return _UN[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    raise ValueError(f"unsupported expression element: {ast.dump(node)[:60]}")


def calculator(expression: str) -> str:
    expr = re.sub(r"(?<=\d),(?=\d{3}\b)", "", str(expression).replace("^", "**"))
    val = _eval(ast.parse(expr, mode="eval"))
    if isinstance(val, float):
        val = round(val, 10)
    if isinstance(val, float) and val.is_integer():
        val = int(val)
    return str(val)


# ---------------------------------------------------------------- docs search
def _load_docs():
    docs = []
    for p in sorted((DATA / "docs").glob("*.md")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                docs.append((p.name, line.strip()))
    return docs


_DOCS = _load_docs()
_STOP = {"the", "a", "an", "of", "is", "what", "for", "on", "in", "to", "and", "how", "many", "does", "plan"}


def _score(query: str, text: str) -> int:
    q = {w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in _STOP}
    t = set(re.findall(r"[a-z0-9]+", text.lower()))
    return len(q & t)


def docs_search(query: str, top_k: int = 3) -> str:
    ranked = sorted(_DOCS, key=lambda d: -_score(query, d[1]))
    hits = [f"[{f}] {t}" for f, t in ranked[: int(top_k)] if _score(query, t) > 0]
    return "\n".join(hits) if hits else "No matching passages."


# ---------------------------------------------------------------- mock web search
_WEB = json.loads((DATA / "web_index.json").read_text(encoding="utf-8"))


def web_search(query: str) -> str:
    ranked = sorted(_WEB, key=lambda d: -_score(query, d["title"] + " " + d["snippet"]))
    hits = [d for d in ranked[:3] if _score(query, d["title"] + " " + d["snippet"]) > 0]
    if not hits:
        return "No results."
    return "\n".join(f"{d['title']} ({d['url']}): {d['snippet']}" for d in hits)


# ---------------------------------------------------------------- optional Tavily
def tavily_search(query: str) -> str:
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        raise RuntimeError("TAVILY_API_KEY is not set; tavily_search is disabled")
    body = json.dumps({"query": query, "max_results": 3, "include_answer": True}).encode()
    req = urllib.request.Request("https://api.tavily.com/search", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    out = [f"Answer: {data.get('answer')}"] if data.get("answer") else []
    out += [f"{x.get('title')} ({x.get('url')}): {x.get('content', '')[:300]}" for x in data.get("results", [])]
    return "\n".join(out) or "No results."


# ---------------------------------------------------------------- KV store (per episode)
class KVStore:
    def __init__(self, initial: dict | None = None):
        self.data = copy.deepcopy(initial or {})

    def get(self, key: str) -> str:
        if key not in self.data:
            return f"ERROR: key '{key}' not found"
        return json.dumps(self.data[key])

    def set(self, key: str, value) -> str:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                pass
        old = self.data.get(key)
        self.data[key] = value
        return f"OK: {key} set (previous value: {json.dumps(old)})"

    def list(self, prefix: str = "") -> str:
        keys = sorted(k for k in self.data if k.startswith(prefix))
        return json.dumps(keys)


SCHEMAS = {
    "calculator": {"description": "Evaluate an arithmetic expression. Supports + - * / ** % sqrt round abs min max.",
                   "parameters": {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]}},
    "docs_search": {"description": "Search the Orbitex internal documentation. Returns matching passages.",
                    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    "web_search": {"description": "Search the web. Returns titles, URLs and snippets.",
                   "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    "tavily_search": {"description": "Live web search via Tavily. Returns an answer and sources.",
                      "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    "kv_get": {"description": "Read the value stored at a key in the key-value store.",
               "parameters": {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}},
    "kv_set": {"description": "Write a value (string, number or JSON) to a key in the key-value store.",
               "parameters": {"type": "object", "properties": {"key": {"type": "string"}, "value": {}}, "required": ["key", "value"]}},
    "kv_list": {"description": "List keys in the key-value store, optionally filtered by prefix.",
                "parameters": {"type": "object", "properties": {"prefix": {"type": "string"}}, "required": []}},
}


def openai_tools(names):
    return [{"type": "function", "function": {"name": n, **SCHEMAS[n]}} for n in names]


class Toolbox:
    """Executes tool calls for one episode and classifies call validity."""

    def __init__(self, allowed, initial_state=None):
        self.allowed = list(allowed)
        self.kv = KVStore(initial_state)

    def call(self, name: str, raw_args: str):
        """Returns (result_text, valid: bool, error_kind | None)."""
        if name not in SCHEMAS:
            return f"ERROR: unknown tool '{name}'", False, "unknown_tool"
        if name not in self.allowed:
            return f"ERROR: tool '{name}' is not available for this task", False, "disallowed_tool"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except (json.JSONDecodeError, ValueError) as e:
            return f"ERROR: malformed arguments ({e})", False, "malformed_args"
        missing = [p for p in SCHEMAS[name]["parameters"].get("required", []) if p not in args]
        if missing:
            return f"ERROR: missing required argument(s): {missing}", False, "missing_args"
        try:
            if name == "calculator":
                out = calculator(args["expression"])
            elif name == "docs_search":
                out = docs_search(args["query"])
            elif name == "web_search":
                out = web_search(args["query"])
            elif name == "tavily_search":
                out = tavily_search(args["query"])
            elif name == "kv_get":
                out = self.kv.get(str(args["key"]))
            elif name == "kv_set":
                out = self.kv.set(str(args["key"]), args["value"])
            else:
                out = self.kv.list(str(args.get("prefix", "")))
        except Exception as e:  # tool ran but failed (e.g. bad expression): call was well-formed
            return f"ERROR: {type(e).__name__}: {e}", True, None
        return out, True, None
