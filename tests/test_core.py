"""Offline tests: run in mock mode, no API key or network needed."""
import json

import pytest

from scaffoldscore.metrics import summarize, wilson
from scaffoldscore.mock_llm import MockLLM
from scaffoldscore.runner import ROOT, run
from scaffoldscore.report import build
from scaffoldscore.scaffolds import Runner
from scaffoldscore.tasks import check, extract_answer, load_tasks
from scaffoldscore.tools import Toolbox, calculator, docs_search, web_search

TASKS = load_tasks(ROOT / "tasks" / "core.yaml")
BY_ID = {t.id: t for t in TASKS}


def test_suite_shape():
    assert 15 <= len(TASKS) <= 25
    assert len({t.category for t in TASKS}) >= 5
    for t in TASKS:
        assert t.decoy != t.gold
        assert t.checks and t.prompt


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t.id)
def test_mock_plan_reaches_gold(task):
    """Executing each task's reference plan with the real tools must yield data that supports gold,
    and the gold answer must pass the checker once the plan's state changes are applied."""
    box = Toolbox(task.tools, task.initial_state)
    outs = []
    for step in task.mock_plan:
        out, valid, _ = box.call(step["tool"], json.dumps(step["args"]))
        assert valid, (task.id, step, out)
        outs.append(out)
    assert check(task, task.gold, box.kv.data), task.id
    assert not check(task, task.decoy, box.kv.data), task.id


def test_calculator_and_search():
    assert calculator("47*389-1205") == "17078"
    assert calculator("round(38000000/64, -3)") == "594000"
    assert "30 days" in docs_search("refund Pro plan")
    assert "1,842" in web_search("Zantor Bridge length")
    with pytest.raises(Exception):
        calculator("__import__('os').system('echo hi')")


def test_tool_validity_classification():
    box = Toolbox(["kv_get"], {"a": 1})
    assert box.call("kv_get", '{"key": "a"}')[1] is True
    assert box.call("kv_get", '{"key": "a"')[2] == "malformed_args"
    assert box.call("kv_get", '{}')[2] == "missing_args"
    assert box.call("calculator", '{"expression": "1"}')[2] == "disallowed_tool"
    assert box.call("rm_rf", '{}')[2] == "unknown_tool"


def test_extract_answer_and_checkers():
    assert extract_answer("blah\nFINAL ANSWER: 1,842 metres") == ("1,842 metres", True)
    t = BY_ID["web-01"]
    assert check(t, "1,842 metres")
    assert not check(t, "either 1842 or 1482")  # hedging with the decoy fails
    assert check(BY_ID["trap-01"], "UNKNOWN") and not check(BY_ID["trap-01"], "30 days")


def test_react_scaffold_with_mock_and_injection():
    llm = MockLLM(TASKS)
    r = Runner(llm, "mock/large", "react", seed=0)
    out = r.run(BY_ID["kv-02"])
    assert out["kv_state"]["config:region"] == "eu-west-2"
    r2 = Runner(llm, "mock/large", "react", seed=0, inject=True, decoy="17178")
    r2.run(BY_ID["math-01"])
    assert r2.ep.injected


def test_end_to_end_mock_run_and_report(tmp_path):
    cfg = tmp_path / "c.yaml"
    cfg.write_text("name: t-MOCK\nmock: true\nrepeats: 2\nmodels: [{name: mock/large, price_in: 1, price_out: 1},"
                   " {name: mock/small}]\nscaffolds: [single_shot, react, plan_execute]\n")
    out = run(cfg, out_dir=tmp_path / "res", log=lambda *a: None)
    recs = [json.loads(l) for l in (out / "results.jsonl").read_text().splitlines()]
    assert recs and all(r["mock"] for r in recs)
    rows = summarize(recs)
    assert len(rows) == 6
    react = {r["agent_id"]: r for r in rows}
    # tools matter: the ReAct agent must beat the no-tool agent on the same (fake) model
    assert react["react@mock/large"]["success"] > react["single_shot@mock/large"]["success"]
    build(out)
    html = (out / "report.html").read_text()
    assert "MOCK RUN" in html and "EXAMPLE DATA ONLY" in html
    assert "MOCK RUN" in (out / "leaderboard.md").read_text()
    # deterministic: same config -> same results
    out2 = run(cfg, out_dir=tmp_path / "res2", log=lambda *a: None)
    key = lambda r: (r["agent_id"], r["task_id"], r["repeat"], r["perturbation"])
    a = sorted(recs, key=key)
    b = sorted((json.loads(l) for l in (out2 / "results.jsonl").read_text().splitlines()), key=key)
    assert [x["success"] for x in a] == [x["success"] for x in b]


def test_wilson():
    lo, hi = wilson(5, 10)
    assert 0.2 < lo < 0.5 < hi < 0.8
