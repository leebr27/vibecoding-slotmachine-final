"""Phase 3: run the baselines and patches under realistic feedback.

Usage:
    python -m harness.evaluate_realistic                  # all variants
    python -m harness.evaluate_realistic --variants slot_machine,attentive --tasks he_fix_spaces

Each (variant, task, session) unit is checkpointed to results/phase3/<variant>.jsonl;
reruns skip finished units. All calls go through the shared call log, so first
attempts that coincide with Phase 1 and Phase 2 draws are replayed, not re-sampled.
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tasks import load_tasks
from .evaluate import k_from_phase1
from .llm_client import LLMClient, make_backend
from .patches import Ctx
from .realistic import N_VISIBLE, VARIANTS, run_variant
from .store import JsonlStore

RESULTS = Path(__file__).resolve().parents[1] / "results"
DEFAULT_SESSIONS = {"slot_machine": 10, "attentive": 10, "retry_budget": 10, "hidden_best_of_n": 10,
                    "test_gated_reveal": 10, "typed_holes_patch": 5, "typed_holes_fixed": 5}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", default="auto")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--variants", default="", help="comma list; default = all variants")
    ap.add_argument("--sessions", type=int, default=0, help="override sessions per task")
    ap.add_argument("--tasks", default="")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--out", default=str(RESULTS))
    args = ap.parse_args(argv)

    out = Path(args.out)
    k_star = k_from_phase1(out, "vibe")
    client = LLMClient(make_backend(args.backend, args.model), out / "raw" / "llm_calls.jsonl")
    ctx = Ctx(client, style="vibe")
    tasks = load_tasks()
    if args.tasks:
        keep = set(args.tasks.split(","))
        tasks = [t for t in tasks if t.task_id in keep]
    variants = args.variants.split(",") if args.variants else list(VARIANTS)
    for v in variants:
        if v not in VARIANTS:
            raise SystemExit(f"unknown variant {v}")

    (out / "phase3").mkdir(parents=True, exist_ok=True)
    (out / "phase3" / "meta.json").write_text(json.dumps(
        {"k_star": k_star, "p1_k": 1, "n_visible": N_VISIBLE, "visible_rule": f"first {N_VISIBLE} tests per task",
         "backend": client.backend.name, "model_alias": client.backend.model, "sessions": DEFAULT_SESSIONS,
         "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, indent=2))

    stores, units = {}, []
    for v in variants:
        store = stores[v] = JsonlStore(out / "phase3" / f"{v}.jsonl")
        done = {(r["task_id"], r["session"]) for r in store.load()}
        n = args.sessions or DEFAULT_SESSIONS[v]
        units += [(v, t, j) for t in tasks for j in range(n) if (t.task_id, j) not in done]
    print(f"{len(units)} session units to run (k*={k_star}, visible tests={N_VISIBLE})", flush=True)

    def work(u):
        v, task, j = u
        rec = run_variant(ctx, v, task, j, k_star).to_dict()
        rec.update(variant=v, k=1 if v == "retry_budget" else k_star)
        return v, rec

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, u): u for u in units}
        for i, fut in enumerate(as_completed(futs), 1):
            u = futs[fut]
            try:
                v, rec = fut.result()
            except Exception as e:  # rerun resumes this unit
                print(f"ERROR {u[0]} {u[1].task_id}#{u[2]}: {e!r}", flush=True)
                continue
            stores[v].append(rec)
            print(f"{i}/{len(units)} {v:18s} {rec['task_id']:26s}#{rec['session']} "
                  f"intent={rec['intent_pass']!s:5s} visible={rec['visible_pass']!s:5s} "
                  f"dp={rec['decision_points']} calls={rec['agent_calls']}+{rec['proxy_calls']} "
                  f"[{time.time() - t0:.0f}s]", flush=True)
    print(f"live LLM calls this run: {client.n_live_calls}")


if __name__ == "__main__":
    main()
