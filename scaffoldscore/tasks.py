"""Task loading and deterministic checkers (no LLM judge)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

FINAL_RE = re.compile(r"final\s*answer\s*[:\-]\s*(.+)", re.I | re.S)


@dataclass
class Task:
    id: str
    category: str
    prompt: str
    tools: list
    gold: str
    checks: list
    decoy: str
    initial_state: dict = field(default_factory=dict)
    mock_plan: list = field(default_factory=list)


def load_tasks(paths) -> list[Task]:
    if isinstance(paths, (str, Path)):
        paths = [paths]
    out = []
    for p in paths:
        data = yaml.safe_load(Path(p).read_text(encoding="utf-8"))
        for t in data["tasks"]:
            out.append(Task(id=t["id"], category=t["category"], prompt=t["prompt"], tools=t.get("tools") or [],
                            gold=str(t["gold"]), checks=t["checks"], decoy=str(t["decoy"]),
                            initial_state=t.get("initial_state") or {}, mock_plan=t.get("mock_plan") or []))
    ids = [t.id for t in out]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate task ids")
    return out


def extract_answer(text: str):
    """Returns (answer, format_ok). Uses the last 'FINAL ANSWER:' if present."""
    text = text or ""
    matches = list(re.finditer(r"final\s*answer\s*[:\-]", text, re.I))
    if matches:
        ans = text[matches[-1].end():].strip().splitlines()
        return (ans[0].strip() if ans else ""), True
    return text.strip(), False


def _numbers(s: str):
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)
    return [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", s)]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9_@.]", "", s.lower()).strip(".")


def check_one(check: dict, answer: str, kv_state: dict) -> bool:
    t = check["type"]
    if t == "number":
        nums = _numbers(answer)
        v = float(check["value"])
        tol = float(check.get("tol", 1e-6)) * max(1.0, abs(v))
        return any(abs(n - v) <= tol for n in nums)
    if t == "contains":
        a = answer.lower()
        return all(str(x).lower() in a for x in check["value"])
    if t == "exact":
        return _norm(answer) == _norm(str(check["value"]))
    if t == "regex":
        return re.search(check["value"], answer, re.I) is not None
    if t == "state":
        return kv_state.get(check["key"]) == check["value"] or str(kv_state.get(check["key"])) == str(check["value"])
    raise ValueError(f"unknown check type {t}")


def check(task: Task, answer: str, kv_state: dict | None = None) -> bool:
    kv_state = kv_state if kv_state is not None else {}
    if not all(check_one(c, answer, kv_state) for c in task.checks):
        return False
    # an answer that also states the decoy number is hedging, not answering
    if any(c["type"] == "number" for c in task.checks):
        dec = _numbers(task.decoy)
        if dec and any(abs(n - dec[0]) < 1e-9 for n in _numbers(answer)):
            return False
    return True


def answer_only_check(task: Task, answer: str) -> bool:
    """Checker ignoring state checks (used for pushback turns, where no tools run)."""
    t2 = Task(**{**task.__dict__, "checks": [c for c in task.checks if c["type"] != "state"]})
    return check(t2, answer, {})
