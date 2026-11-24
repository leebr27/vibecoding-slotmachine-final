"""Phase 1 analysis: is vibecoding a slot machine?

Reads results/phase1/<style>/{blind,error_paste}.jsonl and writes
results/summary/phase1_<style>.json. Every number reported in the paper for
Phase 1 is computed here from the raw attempt logs.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean, median

from harness.metrics import (FAIL, NEAR_MISS, PASS, blind_retry_curve, chain_retry_curve,
                             chains_by_task, cluster_bootstrap, pairwise_similarity,
                             per_task_outcomes, task_stats, transition_stats, wilson)
from harness.store import JsonlStore
from tasks import load_tasks

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def load_phase1(style: str, results: Path = RESULTS) -> tuple[list[dict], list[dict]]:
    d = results / "phase1" / style
    return JsonlStore(d / "blind.jsonl").load(), JsonlStore(d / "error_paste.jsonl").load()


def calibrate_k(hazard: list[float]) -> int:
    """Retry budget for Patch 1, chosen from the error-paste hazard curve.

    Rule (fixed before any patch was evaluated): stop at the first attempt t
    after which the conditional success probability of the next attempt
    falls below half that of the first retry, i.e. the smallest t >= 2 with
    hazard[t+1] < hazard[2] / 2 (1-indexed). Defaults to the last turn."""
    h = hazard
    if len(h) < 3 or not h[1] or math.isnan(h[1]):
        return len(h)
    for t in range(2, len(h)):
        nxt = h[t]
        if math.isnan(nxt) or nxt < h[1] / 2:
            return t
    return len(h)


def summarize(style: str, results: Path = RESULTS, reps: int = 2000) -> dict:
    blind, ep = load_phase1(style, results)
    suites = {t.task_id: t.suite for t in load_tasks()}
    per = per_task_outcomes(blind)
    tasks = sorted(per)
    stats = {tid: task_stats(o) for tid, o in per.items()}
    all_out = [o for tid in tasks for o in per[tid]]
    c = Counter(all_out)
    n_fail = c[NEAR_MISS] + c[FAIL]

    def pooled_nm(ts):
        nm = sum(stats[t]["near_misses"] for t in ts)
        nf = sum(stats[t]["near_misses"] + stats[t]["fails"] for t in ts)
        return nm / nf if nf else float("nan")

    def mean_of(key, ts):
        return mean(stats[t][key] for t in ts)

    summary = {
        "style": style,
        "n_tasks": len(tasks),
        "n_blind_attempts": len(blind),
        "trials_per_task": sorted({len(v) for v in per.values()}),
        "outcome_counts": {PASS: c[PASS], NEAR_MISS: c[NEAR_MISS], FAIL: c[FAIL]},
        "pass_rate": c[PASS] / len(all_out),
        "pass_rate_ci": wilson(c[PASS], len(all_out)),
        "p_nm_given_failure": c[NEAR_MISS] / n_fail if n_fail else None,
        "p_nm_given_failure_ci": [x[0] for x in cluster_bootstrap(tasks, lambda d: [pooled_nm(d)], reps)],
        "mean_bernoulli_var": mean_of("bernoulli_var", tasks),
        "mean_entropy_bits": mean_of("entropy_pass", tasks),
        "mean_entropy_3way_bits": mean_of("entropy_3way", tasks),
        "n_tasks_always_pass": sum(stats[t]["passes"] == stats[t]["n"] for t in tasks),
        "n_tasks_never_pass": sum(stats[t]["passes"] == 0 for t in tasks),
        "n_tasks_stochastic": sum(0 < stats[t]["passes"] < stats[t]["n"] for t in tasks),
        "n_tasks_with_near_miss": sum(stats[t]["near_misses"] > 0 for t in tasks),
        "mean_frac_tests_passed_in_failures": (mean(a["frac"] for a in blind if a["outcome"] != PASS)
                                               if n_fail else None),
        "median_frac_tests_passed_in_failures": (median(a["frac"] for a in blind if a["outcome"] != PASS)
                                                 if n_fail else None),
        "by_suite": {},
        "per_task": {t: {**stats[t], "suite": suites.get(t)} for t in tasks},
    }
    for s in ("humaneval", "mbpp", "original"):
        ts = [t for t in tasks if suites.get(t) == s]
        if not ts:
            continue
        outs = [o for t in ts for o in per[t]]
        cc = Counter(outs)
        summary["by_suite"][s] = {
            "pass_rate": cc[PASS] / len(outs),
            "near_miss_rate": cc[NEAR_MISS] / len(outs),
            "p_nm_given_failure": pooled_nm(ts),
            "mean_entropy_bits": mean_of("entropy_pass", ts),
            "n_stochastic": sum(0 < stats[t]["passes"] < stats[t]["n"] for t in ts),
        }

    # Distinct behaviours among independent pulls of the same prompt.
    by_task_vectors = {}
    for a in blind:
        by_task_vectors.setdefault(a["task_id"], []).append(tuple(a["pass_vector"]))
    summary["mean_distinct_behaviours_per_task"] = mean(len(set(v)) for v in by_task_vectors.values())
    codes = {}
    for a in blind:
        codes.setdefault(a["task_id"], []).append(a["code"])
    summary["mean_pairwise_code_similarity_blind"] = mean(
        x for x in (pairwise_similarity(v) for v in codes.values()) if x is not None)

    # Retry curves.
    max_t = 5
    bc = blind_retry_curve(per, max_t)
    blo, bhi = cluster_bootstrap(tasks, lambda d: blind_retry_curve(per, max_t, d)["hazard"], reps)
    summary["blind_curve"] = {**bc, "hazard_ci_lo": blo, "hazard_ci_hi": bhi}
    if ep:
        chains = chains_by_task(ep)
        ec = chain_retry_curve(chains, max_t)
        elo, ehi = cluster_bootstrap(sorted(chains), lambda d: chain_retry_curve(chains, max_t, d)["hazard"], reps)
        summary["error_paste_curve"] = {**ec, "hazard_ci_lo": elo, "hazard_ci_hi": ehi}
        summary["error_paste_transitions"] = transition_stats(chains)
        turns = [len(ch) for chs in chains.values() for ch in chs]
        final = [ch[-1]["outcome"] for chs in chains.values() for ch in chs]
        summary["error_paste_sessions"] = {
            "n": len(turns), "mean_turns": mean(turns),
            "final_pass_rate": sum(f == PASS for f in final) / len(final),
            "n_exhausted": sum(f != PASS for f in final),
            "visible_near_misses_per_session": mean(
                sum(a["outcome"] == NEAR_MISS for a in ch) for chs in chains.values() for ch in chs),
            "visible_near_misses_per_session_given_any_failure": mean(
                [sum(a["outcome"] == NEAR_MISS for a in ch) for chs in chains.values() for ch in chs
                 if ch[0]["outcome"] != PASS] or [0]),
        }
        summary["k_star"] = calibrate_k(ec["hazard"])
    return summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--style", default="vibe")
    ap.add_argument("--reps", type=int, default=2000)
    args = ap.parse_args(argv)
    s = summarize(args.style, reps=args.reps)
    out = RESULTS / "summary"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"phase1_{args.style}.json").write_text(json.dumps(s, indent=2))
    keys = ["n_blind_attempts", "outcome_counts", "pass_rate", "p_nm_given_failure", "mean_entropy_bits",
            "n_tasks_stochastic", "k_star"]
    print(json.dumps({k: s.get(k) for k in keys}, indent=2))
    if "error_paste_curve" in s:
        print("blind hazard", [round(x, 3) for x in s["blind_curve"]["hazard"]])
        print("ep hazard   ", [round(x, 3) for x in s["error_paste_curve"]["hazard"]])
        print("ep reached  ", s["error_paste_curve"]["reached"])


if __name__ == "__main__":
    main()
