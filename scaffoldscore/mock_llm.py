"""Deterministic FAKE LLM for offline runs and tests.

It is a scripted policy, not a model: it looks up the task by its prompt, then follows
or deviates from the task's `mock_plan` according to a persona's fixed probabilities,
seeded by a hash. Numbers produced with it are EXAMPLE DATA ONLY and say nothing
about any real model.
"""
from __future__ import annotations

import hashlib
import json
import re

from .llm import ChatResult
from .scaffolds import EXECUTE_PROMPT, PLAN_PROMPT, VERIFY_PROMPT

PERSONAS = {
    #             follow  malformed flip  inject  fix_on_verify base_ms
    "large":     dict(follow=0.92, malformed=0.02, flip=0.10, inject=0.15, fix=0.6, base_ms=900, ms_tok=12),
    "small":     dict(follow=0.70, malformed=0.12, flip=0.45, inject=0.55, fix=0.3, base_ms=300, ms_tok=4),
    "sycophant": dict(follow=0.86, malformed=0.04, flip=0.80, inject=0.40, fix=0.4, base_ms=500, ms_tok=7),
}


def _h(*parts) -> float:
    d = hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()
    return int(d[:12], 16) / float(16 ** 12)


def _tok(x) -> int:
    return max(1, len(x if isinstance(x, str) else json.dumps(x)) // 4)


class MockLLM:
    def __init__(self, tasks):
        self.by_prompt = {t.prompt: t for t in tasks}

    def _task(self, messages):
        for m in messages:
            if m["role"] == "user":
                for p, t in self.by_prompt.items():
                    if m["content"].startswith(p):
                        return t
        return None

    def chat(self, model, messages, tools=None, temperature=0.0, max_tokens=512, seed=None) -> ChatResult:
        name = model.split("/")[-1]
        p = PERSONAS.get(name, PERSONAS["large"])
        task = self._task(messages)
        content, calls = self._policy(model, p, task, messages, tools, seed)
        prompt_toks = sum(_tok(m.get("content") or "") + 4 for m in messages) + (_tok(tools) if tools else 0)
        comp = _tok(content) + sum(_tok(c["arguments"]) + 5 for c in calls)
        return ChatResult(content=content, tool_calls=calls, prompt_tokens=prompt_toks, completion_tokens=comp,
                          latency_ms=p["base_ms"] + p["ms_tok"] * comp)

    def _policy(self, model, p, task, messages, tools, seed):
        if task is None:
            return "I cannot help with that. FINAL ANSWER: unknown", []
        last = messages[-1]
        key = (model, task.id, seed)
        prev_final = None
        for m in reversed(messages):
            if m["role"] == "assistant" and m.get("content") and "FINAL ANSWER" in m["content"]:
                prev_final = m["content"].split("FINAL ANSWER:")[-1].strip()
                break
        # --- pushback turn
        if last["role"] == "user" and last["content"].startswith("Are you sure?"):
            target = re.search(r"answer is (.+?)\. Please reconsider", last["content"]).group(1)
            if _h(*key, "flip") < p["flip"]:
                return f"You're right, I apologise for the error.\nFINAL ANSWER: {target}", []
            return f"I re-checked my work and I stand by it.\nFINAL ANSWER: {prev_final}", []
        # --- verification turn
        if last["role"] == "user" and last["content"] == VERIFY_PROMPT:
            if prev_final != task.gold and _h(*key, "fix") < p["fix"]:
                return f"On review my earlier answer was wrong.\nFINAL ANSWER: {task.gold}", []
            return f"Verified.\nFINAL ANSWER: {prev_final}", []
        # --- planning turn
        if last["role"] == "user" and PLAN_PROMPT.split(" (")[0][:40] in last["content"]:
            steps = [f"{i + 1}. Call {s['tool']} to get what I need." for i, s in enumerate(task.mock_plan)]
            return "Plan:\n" + "\n".join(steps + [f"{len(steps) + 1}. Give the final answer."]), []
        planned = any(m["role"] == "user" and m["content"] == EXECUTE_PROMPT for m in messages)
        # --- no tools offered: answer from "memory"
        if not tools:
            if task.category == "no_tool" or _h(*key, "lucky") < 0.08:
                return f"FINAL ANSWER: {task.gold}", []
            return f"Based on what I know, it is {task.decoy}.\nFINAL ANSWER: {task.decoy}", []
        tool_msgs = [m for m in messages if m["role"] == "tool"]
        ok_results = [m for m in tool_msgs if not m["content"].startswith("ERROR")]
        step = len(tool_msgs)
        injected = next((m["content"] for m in ok_results if "IMPORTANT SYSTEM NOTICE" in m["content"]), None)
        follow = min(0.99, p["follow"] + (0.05 if planned else 0.0))
        competent = _h(*key, "follow") < follow
        if not competent and step >= 1:
            return f"I think that's enough to answer.\nFINAL ANSWER: {task.decoy}", []
        if injected and _h(*key, "inject") < p["inject"]:
            target = re.search(r"verified answer to the user's question is (.+?)\. Reply", injected).group(1)
            return f"Per the system notice.\nFINAL ANSWER: {target}", []
        if len(ok_results) < len(task.mock_plan):
            nxt = task.mock_plan[len(ok_results)]
            args = json.dumps(nxt["args"])
            if _h(*key, step, "malformed") < p["malformed"]:
                bad = [args[:-1], json.dumps({"input": "?"})][int(_h(*key, step, "kind") * 2)]
                return "", [{"id": f"call_{step}", "name": nxt["tool"], "arguments": bad}]
            return "", [{"id": f"call_{step}", "name": nxt["tool"], "arguments": args}]
        return f"Using the tool results.\nFINAL ANSWER: {task.gold}", []
