"""Phase 2: evaluate the baseline and the four patches on the benchmark.

Usage:
    python -m harness.evaluate                      # all conditions, k from Phase 1
    python -m harness.evaluate --variants retry_budget:1,retry_budget:2   # k sweep

Each (condition, task, session) unit is checkpointed to
results/phase2/<variant>.jsonl; reruns skip finished units. All LLM calls go
through the shared call log, so draws that coincide with Phase 1 (same prompt,
same sample index) are replayed rather than re-sampled.
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tasks import load_tasks
from .llm_client import LLMClient, make_backend
from .patches import CONDITIONS, Ctx, run_condition
from .store import JsonlStore

RESULTS = Path(__file__).resolve().parents[1] / "results"
DEFAULT_SESSIONS = {"slot_machine": 10, "retry_budget": 10, "hidden_best_of_n": 10,
                    "test_gated_reveal": 10, "typed_holes_patch": 5}


def k_from_phase1(results: Path, style: str) -> int:
    p = results / "summary" / f"phase1_{style}.json"
    if not p.exists():
        raise SystemExit(f"{p} missing: run `python -m analysis.phase1 --style {style}` first")
    return int(json.loads(p.read_text())["k_star"])


def variant_name(condition: str, k: int, k_star: int) -> str:
    return condition if k == k_star else f"{condition}_k{k}"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default="auto")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--style", default="vibe", choices=["vibe", "spec"])
    ap.add_argument("--k", default="auto", help="retry budget / rounds; 'auto' = Phase 1 calibration")
    ap.add_argument("--variants", default="", help="comma list of condition[:k]; default = all conditions at k*")
    ap.add_argument("--sessions", type=int, default=0, help="override sessions per task for every condition")
    ap.add_argument("--tasks", default="")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default=str(RESULTS))
    args = ap.parse_args(argv)

    out = Path(args.out)
    k_star = k_from_phase1(out, args.style) if args.k == "auto" else int(args.k)
    client = LLMClient(make_backend(args.backend, args.model), out / "raw" / "llm_calls.jsonl")
    ctx = Ctx(client, style=args.style)
    tasks = load_tasks()
    if args.tasks:
        keep = set(args.tasks.split(","))
        tasks = [t for t in tasks if t.task_id in keep]

    specs = []
    for item in (args.variants.split(",") if args.variants else CONDITIONS):
        cond, _, kk = item.partition(":")
        if cond not in CONDITIONS:
            raise SystemExit(f"unknown condition {cond}")
        specs.append((cond, int(kk) if kk else k_star))

    (out / "phase2").mkdir(parents=True, exist_ok=True)
    (out / "phase2" / "meta.json").write_text(json.dumps(
        {"k_star": k_star, "style": args.style, "backend": client.backend.name,
         "model_alias": client.backend.model, "sessions": DEFAULT_SESSIONS,
         "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, indent=2))

    units = []
    stores = {}
    for cond, k in specs:
        name = variant_name(cond, k, k_star)
        store = stores[name] = JsonlStore(out / "phase2" / f"{name}.jsonl")
        done = {(r["task_id"], r["session"]) for r in store.load()}
        n = args.sessions or DEFAULT_SESSIONS[cond]
        units += [(name, cond, k, t, j) for t in tasks for j in range(n) if (t.task_id, j) not in done]
    print(f"{len(units)} session units to run (k*={k_star})", flush=True)

    def work(u):
        name, cond, k, task, j = u
        rec = run_condition(ctx, cond, task, j, k).to_dict()
        rec.update(variant=name, k=k)
        return name, rec

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, u): u for u in units}
        for i, fut in enumerate(as_completed(futs), 1):
            u = futs[fut]
            try:
                name, rec = fut.result()
            except Exception as e:  # rerun resumes this unit
                print(f"ERROR {u[0]} {u[3].task_id}#{u[4]}: {e!r}", flush=True)
                continue
            stores[name].append(rec)
            print(f"{i}/{len(units)} {name:24s} {rec['task_id']:26s}#{rec['session']} "
                  f"pass={rec['final_pass']!s:5s} pulls={rec['n_pulls']} nm={rec['visible_near_misses']} "
                  f"dp={rec['decision_points']} calls={rec['agent_calls']}+{rec['proxy_calls']} "
                  f"[{time.time() - t0:.0f}s]", flush=True)
    print(f"live LLM calls this run: {client.n_live_calls}")


if __name__ == "__main__":
    main()
