"""Phase 1: measure the slot-machine baseline.

Regime A (blind pull): the identical task prompt is sampled N times, as if the
user kept pressing "regenerate".

Regime B (error-paste loop): starting from each blind pull, a simulated
passive user pastes the raw pytest failure output back and asks for a fix,
for up to k turns or until all tests pass. Turn 1 of chain c is, by
construction, blind pull c (same prompt, same sample index), so the two
regimes share their first draw.

Usage:
    python -m harness.runner --trials 10 --chains 10 --max-turns 5 --workers 6
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from tasks import Task, load_tasks
from .codeutil import extract_code
from .llm_client import LLMClient, LLMResponse, make_backend
from .metrics import PASS, classify
from .prompts import SYSTEM_CODER, error_paste_prompt, task_prompt
from .sandbox import ExecResult, run_tests
from .store import JsonlStore

RESULTS = Path(__file__).resolve().parents[1] / "results"


@dataclass
class Generation:
    resp: LLMResponse
    code: str
    result: ExecResult
    outcome: str


def llm_meta(resp: LLMResponse) -> dict:
    return {"key": resp.key, "model": resp.model, "backend": resp.backend, "sample": resp.sample,
            "tag": resp.tag, "input_tokens": resp.total_input_tokens, "output_tokens": resp.output_tokens,
            "cost_usd": resp.cost_usd, "latency_s": round(resp.latency_s, 3), "cached": resp.cached}


def generate_and_test(client: LLMClient, task: Task, prompt: str, sample: int, tag: str,
                      system: str = SYSTEM_CODER) -> Generation:
    resp = client.complete(prompt, system, sample=sample, tag=tag)
    code = extract_code(resp.text)
    result = run_tests(code, task)
    return Generation(resp, code, result, classify(result.n_pass, result.n_total, result.syntax_ok))


def attempt_record(task: Task, regime: str, chain: int, turn: int, g: Generation,
                   style: str = "vibe") -> dict:
    return {
        "task_id": task.task_id, "suite": task.suite, "regime": regime, "prompt_style": style,
        "chain": chain, "turn": turn,
        "outcome": g.outcome, "n_pass": g.result.n_pass, "n_total": g.result.n_total,
        "frac": round(g.result.frac, 4), "pass_vector": list(g.result.pass_vector()),
        "failed_tests": [o.name for o in g.result.failed()],
        "error_types": sorted({o.error_type for o in g.result.failed() if o.error_type}),
        "load_error": g.result.load_error, "sandbox_s": g.result.wall_s,
        "code": g.code, "response_text": g.resp.text, "llm": llm_meta(g.resp),
        "exec": g.result.to_dict(),
    }


# ---------------------------------------------------------------------------
def run_blind_unit(client: LLMClient, task: Task, trial: int, style: str = "vibe") -> list[dict]:
    g = generate_and_test(client, task, task_prompt(task, style), sample=trial, tag=f"blind:{style}")
    return [attempt_record(task, "blind", trial, 1, g, style)]


def run_error_paste_unit(client: LLMClient, task: Task, chain: int, max_turns: int,
                         style: str = "vibe") -> list[dict]:
    recs, history = [], []
    for turn in range(1, max_turns + 1):
        prompt = task_prompt(task, style) if turn == 1 else error_paste_prompt(task, history, style)
        g = generate_and_test(client, task, prompt, sample=chain,
                              tag=f"blind:{style}" if turn == 1 else f"error_paste:{style}")
        recs.append(attempt_record(task, "error_paste", chain, turn, g, style))
        if g.outcome == PASS:
            break
        history.append((g.code, g.result.failure_report(task)))
    return recs


def _run_units(units, fn, store: JsonlStore, workers: int, label: str) -> None:
    done = {(r["task_id"], r["chain"]) for r in store.load()}
    todo = [u for u in units if (u[0].task_id, u[1]) not in done]
    print(f"[{label}] {len(units) - len(todo)} units already done, {len(todo)} to run", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fn, *u): u for u in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            u = futs[fut]
            try:
                recs = fut.result()
            except Exception as e:  # keep going; a rerun resumes the failed unit
                print(f"[{label}] ERROR {u[0].task_id}#{u[1]}: {e}", flush=True)
                continue
            store.append_many(recs)
            last = recs[-1]
            print(f"[{label}] {i}/{len(todo)} {u[0].task_id}#{u[1]} turns={len(recs)} "
                  f"-> {last['outcome']} ({last['n_pass']}/{last['n_total']}) "
                  f"[{time.time() - t0:.0f}s]", flush=True)


def write_meta(out_dir: Path, client: LLMClient, args: argparse.Namespace) -> None:
    meta = {"backend": client.backend.name, "model_alias": client.backend.model,
            "python": sys.version.split()[0], "platform": platform.platform(),
            "args": {k: (os.path.relpath(v, RESULTS.parent) if k == "out" else v)
                     for k, v in vars(args).items()}, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    binary = getattr(client.backend, "binary", None)
    if binary:
        try:
            meta["claude_cli_version"] = subprocess.run([binary, "--version"], capture_output=True,
                                                        text=True, timeout=30).stdout.strip()
        except Exception:
            pass
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default="auto")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--trials", type=int, default=10, help="blind pulls per task")
    ap.add_argument("--chains", type=int, default=10, help="error-paste chains per task")
    ap.add_argument("--max-turns", type=int, default=5)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--tasks", default="", help="comma-separated task ids (default: all)")
    ap.add_argument("--out", default=str(RESULTS))
    ap.add_argument("--skip-error-paste", action="store_true")
    ap.add_argument("--prompt-style", default="vibe", choices=["vibe", "spec"])
    args = ap.parse_args(argv)

    out = Path(args.out)
    style = args.prompt_style
    p1 = out / "phase1" / style
    p1.mkdir(parents=True, exist_ok=True)
    client = LLMClient(make_backend(args.backend, args.model), out / "raw" / "llm_calls.jsonl")
    tasks = load_tasks()
    if args.tasks:
        wanted = set(args.tasks.split(","))
        tasks = [t for t in tasks if t.task_id in wanted]
    write_meta(p1, client, args)

    blind = JsonlStore(p1 / "blind.jsonl")
    _run_units([(t, i) for t in tasks for i in range(args.trials)],
               lambda task, i: run_blind_unit(client, task, i, style), blind, args.workers, f"blind:{style}")
    if not args.skip_error_paste:
        ep = JsonlStore(p1 / "error_paste.jsonl")
        _run_units([(t, c) for t in tasks for c in range(args.chains)],
                   lambda task, c: run_error_paste_unit(client, task, c, args.max_turns, style),
                   ep, args.workers, f"error-paste:{style}")
    print(f"live LLM calls this run: {client.n_live_calls}")


if __name__ == "__main__":
    main()
