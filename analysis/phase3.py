"""Phase 3 analysis: the patches under realistic feedback.

Reads results/phase3/<variant>.jsonl and writes results/summary/phase3.json.

Primary outcome: intent pass, i.e. the final program passes the full hidden suite,
of which the programmer only ever saw the first N_VISIBLE tests. A silent failure
is a final program that passes every visible test but not the full suite: it
looks finished and is wrong (a loss disguised as a win).

Differences from the vibecoder baseline are paired by task and bootstrapped over
tasks (2,000 replicates), so the interval reflects task-to-task variation.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

from analysis.phase2 import contested_tasks, summarize_variant
from harness.metrics import cluster_bootstrap, wilson
from harness.store import JsonlStore

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
ORDER = ["slot_machine", "attentive", "retry_budget", "hidden_best_of_n", "test_gated_reveal",
         "typed_holes_patch", "typed_holes_fixed"]
LABELS = {"slot_machine": "Vibecoder (paste errors)", "attentive": "Attentive programmer",
          "retry_budget": "P1 Retry budget (k=1)", "hidden_best_of_n": "P2 Hidden best-of-5",
          "test_gated_reveal": "P3 Test-gated reveal", "typed_holes_patch": "P4 Typed holes",
          "typed_holes_fixed": "P4 + hole requests"}


def _task_rate(recs: list[dict], key: str) -> dict[str, float]:
    by = defaultdict(list)
    for r in recs:
        by[r["task_id"]].append(bool(r[key]))
    return {t: mean(v) for t, v in by.items()}


def paired_delta(recs: list[dict], base: list[dict], key: str = "intent_pass", reps: int = 2000) -> dict:
    """Mean per-task difference in `key` against the baseline, with a task-bootstrap 95% CI."""
    a, b = _task_rate(recs, key), _task_rate(base, key)
    tasks = sorted(set(a) & set(b))
    if not tasks:
        return {"delta": None, "lo": None, "hi": None, "n_tasks": 0}
    diff = {t: a[t] - b[t] for t in tasks}
    lo, hi = cluster_bootstrap(tasks, lambda d: [mean(diff[t] for t in d)], reps)
    return {"delta": mean(diff.values()), "lo": lo[0], "hi": hi[0], "n_tasks": len(tasks)}


def summarize_realistic(recs: list[dict], contested: list[str], reps: int = 1000) -> dict:
    out = summarize_variant(recs, reps)  # final_pass == intent pass; visible signals are visible-test outcomes
    n = len(recs)
    k_int = sum(r["intent_pass"] for r in recs)
    vis_done = [r for r in recs if r["visible_pass"]]
    tasks = sorted({r["task_id"] for r in recs})
    rate = _task_rate(recs, "intent_pass")
    lo, hi = cluster_bootstrap(tasks, lambda d: [mean(rate[t] for t in d)], reps)
    con = [r for r in recs if r["task_id"] in set(contested)]
    reviews = [ok for r in recs for ok in r["extra"].get("diagnoses_accepted", [])]
    requests = [r for r in recs if r["extra"].get("hole_request")]
    out.update({
        "intent_pass_rate": k_int / n, "intent_pass_ci": wilson(k_int, n),
        "intent_pass_boot_ci": [lo[0], hi[0]],
        "visible_pass_rate": len(vis_done) / n,
        "silent_failure_rate": mean(r["silent_failure"] for r in recs),
        "silent_given_visible_pass": (mean(r["silent_failure"] for r in vis_done) if vis_done else None),
        "human_turns_per_session": mean(r["human_turns"] for r in recs),
        "shown_lines_per_session": mean(r["shown_lines"] for r in recs),
        "clarifications_per_session": mean(len(r["extra"].get("clarifications", [])) for r in recs),
        "contested_n_tasks": len({r["task_id"] for r in con}),
        "contested_intent_pass_rate": mean(r["intent_pass"] for r in con) if con else None,
        "contested_silent_failure_rate": mean(r["silent_failure"] for r in con) if con else None,
        "diagnoses_reviewed": len(reviews),
        "diagnoses_accepted_rate": mean(reviews) if reviews else None,
        "n_hole_requests": len(requests),
        "hole_request_pass_rate": mean(r["intent_pass"] for r in requests) if requests else None,
    })
    return out


def load(name: str, results: Path = RESULTS) -> list[dict]:
    return JsonlStore(results / "phase3" / f"{name}.jsonl").load()


def summarize(results: Path = RESULTS, reps: int = 1000) -> dict:
    contested = contested_tasks(results)
    variants = {}
    for name in ORDER:
        recs = load(name, results)
        if recs:
            variants[name] = summarize_realistic(recs, contested, reps)
    base = load("slot_machine", results)
    if base:
        for name in variants:
            recs = load(name, results)
            variants[name]["delta_intent_vs_vibecoder"] = paired_delta(recs, base, "intent_pass", 2 * reps)
            variants[name]["delta_silent_vs_vibecoder"] = paired_delta(recs, base, "silent_failure", 2 * reps)
            cbase = [r for r in base if r["task_id"] in set(contested)]
            crec = [r for r in recs if r["task_id"] in set(contested)]
            variants[name]["contested_delta_intent"] = paired_delta(crec, cbase, "intent_pass", 2 * reps)
        b = variants["slot_machine"]
        for v in variants.values():
            v["token_ratio_vs_vibecoder"] = (v["agent_tokens_per_session"] / b["agent_tokens_per_session"]
                                             if b["agent_tokens_per_session"] else None)
    meta_p = results / "phase3" / "meta.json"
    return {"meta": json.loads(meta_p.read_text()) if meta_p.exists() else {}, "contested_tasks": contested,
            "variants": variants, "order": [o for o in ORDER if o in variants], "labels": LABELS}


def main():
    s = summarize()
    out = RESULTS / "summary"
    out.mkdir(parents=True, exist_ok=True)
    (out / "phase3.json").write_text(json.dumps(s, indent=2))
    cols = ["n_sessions", "intent_pass_rate", "visible_pass_rate", "silent_failure_rate",
            "visible_near_misses_per_session", "decision_points_per_session", "human_turns_per_session",
            "agent_tokens_per_session", "contested_intent_pass_rate"]
    print("variant".ljust(20) + "".join(c[:11].rjust(12) for c in cols) + "   delta [95% CI]")
    for name in s["order"]:
        v = s["variants"][name]
        d = v.get("delta_intent_vs_vibecoder", {})
        print(name.ljust(20) + "".join(f"{v[c]:12.3f}" if isinstance(v[c], float) else f"{v[c]:12d}"
                                       for c in cols)
              + (f"   {d['delta']:+.3f} [{d['lo']:+.3f}, {d['hi']:+.3f}]" if d.get("delta") is not None else ""))


if __name__ == "__main__":
    main()
