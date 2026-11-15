"""Runs a benchmark config: agents x tasks x repeats x perturbations -> results.jsonl."""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml

from . import __version__
from .llm import OpenAICompatClient
from .mock_llm import MockLLM
from .scaffolds import Runner
from .tasks import answer_only_check, check, load_tasks

ROOT = Path(__file__).resolve().parent.parent


def load_config(path):
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    cfg.setdefault("repeats", 3)
    cfg.setdefault("temperature", 0.7)
    cfg.setdefault("max_steps", 8)
    cfg.setdefault("max_tokens", 512)
    cfg.setdefault("concurrency", 4)
    cfg.setdefault("perturbations", ["pushback", "injection"])
    cfg.setdefault("tasks", ["tasks/core.yaml"])
    cfg.setdefault("gateway", {"base_url": "http://localhost:8080/v1"})
    if "agents" not in cfg:
        cfg["agents"] = [{"model": m["name"], "scaffold": s} for m in cfg["models"] for s in cfg["scaffolds"]]
    prices = {m["name"]: m for m in cfg.get("models", [])}
    for a in cfg["agents"]:
        a.setdefault("id", f"{a['scaffold']}@{a['model']}")
        p = prices.get(a["model"], {})
        a.setdefault("price_in", p.get("price_in"))
        a.setdefault("price_out", p.get("price_out"))
    return cfg


def make_llm(cfg, tasks, mock: bool, base_url: str | None = None):
    if mock:
        return MockLLM(tasks)
    gw = cfg["gateway"]
    key = os.environ.get(gw.get("api_key_env", "BIFROST_API_KEY")) or None
    headers = {}
    vk = os.environ.get(gw.get("virtual_key_env", "BIFROST_VIRTUAL_KEY"))
    if vk:  # Bifrost virtual key (needed when inference auth is on)
        headers["x-bf-vk"] = vk
    return OpenAICompatClient(base_url or gw["base_url"], api_key=key, timeout=gw.get("timeout", 120),
                              extra_headers=headers)


def _cost(ep, agent):
    if ep.cost_reported:
        return ep.cost_usd, "gateway"
    if agent.get("price_in") is not None and agent.get("price_out") is not None:
        return (ep.prompt_tokens * agent["price_in"] + ep.completion_tokens * agent["price_out"]) / 1e6, "price_table"
    return None, "unknown"


def run_episode(llm, cfg, agent, task, repeat, perturbation, mock):
    r = Runner(llm, agent["model"], agent["scaffold"], temperature=cfg["temperature"],
               max_tokens=cfg["max_tokens"], max_steps=cfg["max_steps"], seed=repeat,
               inject=(perturbation == "injection"), decoy=task.decoy)
    out = r.run(task)
    success = bool(out["answer"]) and check(task, out["answer"], out["kv_state"])
    rec = {"agent_id": agent["id"], "model": agent["model"], "scaffold": agent["scaffold"], "task_id": task.id,
           "category": task.category, "repeat": repeat, "perturbation": perturbation, "mock": mock,
           "answer": out["answer"], "gold": task.gold, "success": success, "format_ok": out["format_ok"]}
    if perturbation == "injection":
        rec["injected"] = r.ep.injected
        rec["hijacked"] = r.ep.injected and task.decoy.lower() in out["answer"].lower()
    pb_transcript = None
    ep = r.ep
    main = dict(steps=ep.llm_calls, prompt_tokens=ep.prompt_tokens, completion_tokens=ep.completion_tokens,
                latency_ms=ep.latency_ms, cost_usd=ep.cost_usd, cost_reported=ep.cost_reported, error=ep.error)
    if perturbation == "none" and "pushback" in cfg["perturbations"] and out["answer"] and not r.ep.error:
        target = task.decoy if success else task.gold
        ans2, pb_transcript = r.pushback(out["messages"], target)
        after = answer_only_check(task, ans2)
        rec["pushback"] = {"kind": "capitulation_test" if success else "warranted_test", "target": target,
                           "answer": ans2, "success_after": after,
                           "flipped": after != success}
    # steps/tokens/cost/latency cover the task episode only; the pushback turn is excluded
    m = type("M", (), main)
    cost, cost_src = _cost(m, agent)
    rec.update({"steps": main["steps"], "tool_calls": ep.tool_calls, "valid_tool_calls": ep.valid_tool_calls,
                "invalid_kinds": ep.invalid_kinds, "prompt_tokens": main["prompt_tokens"],
                "completion_tokens": main["completion_tokens"], "cost_usd": cost, "cost_source": cost_src,
                "latency_ms": round(main["latency_ms"], 1), "error": main["error"] or ep.error})
    transcript = {"agent_id": agent["id"], "task_id": task.id, "repeat": repeat, "perturbation": perturbation,
                  "messages": pb_transcript or out["messages"]}
    return rec, transcript


def run(config_path, mock=False, out_dir=None, limit=None, base_url=None, log=print):
    cfg = load_config(config_path)
    fake_backend = bool(cfg.get("label_mock"))  # real HTTP path, but the upstream is the fake LLM server
    mock = mock or bool(cfg.get("mock"))
    tasks = load_tasks([ROOT / t if not Path(t).is_absolute() else t for t in cfg["tasks"]])
    if limit:
        tasks = tasks[:limit]
    llm = make_llm(cfg, tasks, mock, base_url)
    name = cfg.get("name", Path(config_path).stem) + ("-MOCK" if mock and "mock" not in cfg.get("name", "").lower() else "")
    out = Path(out_dir or ROOT / "results" / name)
    out.mkdir(parents=True, exist_ok=True)
    res_path, tr_path = out / "results.jsonl", out / "transcripts.jsonl"
    done = set()
    if res_path.exists():
        for line in res_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                done.add((d["agent_id"], d["task_id"], d["repeat"], d["perturbation"]))
    perts = ["none"] + (["injection"] if "injection" in cfg["perturbations"] else [])
    jobs = [(a, t, k, p) for a in cfg["agents"] for t in tasks for k in range(cfg["repeats"]) for p in perts
            if not (p == "injection" and not t.tools) and (a["id"], t.id, k, p) not in done]
    meta = {"name": name, "mock": mock or fake_backend, "fake_upstream_via_gateway": fake_backend, "version": __version__, "config": cfg,
            "started": dt.datetime.now(dt.timezone.utc).isoformat(), "n_tasks": len(tasks),
            "gateway": None if mock else (base_url or cfg["gateway"]["base_url"])}
    (out / "meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
    log(f"[scaffoldscore] {'MOCK (fake LLM, example data only)' if mock else 'LIVE via ' + meta['gateway']}: "
        f"{len(cfg['agents'])} agents x {len(tasks)} tasks x {cfg['repeats']} repeats -> {len(jobs)} episodes "
        f"({len(done)} already done) -> {out}")
    lock = threading.Lock()
    n = 0
    with open(res_path, "a", encoding="utf-8") as fr, open(tr_path, "a", encoding="utf-8") as ft, \
            ThreadPoolExecutor(max_workers=1 if mock else cfg["concurrency"]) as pool:
        futs = [pool.submit(run_episode, llm, cfg, *j, mock or fake_backend) for j in jobs]
        for f in as_completed(futs):
            rec, tr = f.result()
            with lock:
                fr.write(json.dumps(rec) + "\n")
                ft.write(json.dumps(tr) + "\n")
                n += 1
                if n % 100 == 0 or n == len(jobs):
                    log(f"  {n}/{len(jobs)} episodes")
    return out
