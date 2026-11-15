"""scaffoldscore CLI: run | report | list-tasks | models | mock-server"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .runner import ROOT


def main(argv=None):
    ap = argparse.ArgumentParser(prog="scaffoldscore", description="Benchmark AI agents, not just models.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run a benchmark config")
    r.add_argument("--config", required=True)
    r.add_argument("--mock", action="store_true", help="use the deterministic fake LLM (no API key, example data)")
    r.add_argument("--out", help="output dir (default results/<name>)")
    r.add_argument("--limit", type=int, help="only the first N tasks (quick trial)")
    r.add_argument("--base-url", help="override gateway base URL (default from config, Bifrost http://localhost:8080/v1)")
    r.add_argument("--no-report", action="store_true")
    p = sub.add_parser("report", help="build leaderboard + HTML report from a results dir")
    p.add_argument("run_dir", nargs="?", help="results/<name> (default: newest)")
    sub.add_parser("list-tasks")
    m = sub.add_parser("models", help="list models the gateway exposes")
    m.add_argument("--base-url", default="http://localhost:8080/v1")
    s = sub.add_parser("mock-server", help="serve the fake LLM as an OpenAI-compatible API (to test Bifrost routing)")
    s.add_argument("--port", type=int, default=9100)
    a = ap.parse_args(argv)

    if a.cmd == "run":
        from .report import build
        from .runner import run
        out = run(a.config, mock=a.mock, out_dir=a.out, limit=a.limit, base_url=a.base_url)
        if not a.no_report:
            build(out)
            print(f"[scaffoldscore] report: {out / 'report.html'}\n[scaffoldscore] leaderboard: {out / 'leaderboard.md'}")
    elif a.cmd == "report":
        from .report import build
        rd = a.run_dir
        if not rd:
            dirs = sorted((ROOT / "results").glob("*/results.jsonl"), key=lambda p: p.stat().st_mtime)
            if not dirs:
                sys.exit("no results found; run `scaffoldscore run` first")
            rd = dirs[-1].parent
        out = build(rd)
        print(f"[scaffoldscore] report: {Path(out) / 'report.html'}")
    elif a.cmd == "list-tasks":
        from .tasks import load_tasks
        for t in load_tasks(ROOT / "tasks" / "core.yaml"):
            print(f"{t.id:10s} {t.category:8s} tools={','.join(t.tools) or '-':28s} {t.prompt[:70]}")
    elif a.cmd == "models":
        from .llm import OpenAICompatClient
        for mid in OpenAICompatClient(a.base_url).list_models():
            print(mid)
    elif a.cmd == "mock-server":
        from .mock_server import serve
        serve(a.port)


if __name__ == "__main__":
    main()
