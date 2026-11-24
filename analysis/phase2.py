"""Phase 2 analysis: what each patch shows the programmer, and what it costs.

Reads results/phase2/<variant>.jsonl and writes results/summary/phase2.json.

Definitions (per session unless stated):
  visible generation event  a model generation whose result the programmer is
                            shown: a complete program with its test outcome
                            (pass / near-miss / fail), or under Patch 3 a
                            withheld attempt ("hidden") or a revealed pass.
  visible entropy           per task, Shannon entropy (bits) of the categorical
                            distribution of visible signals over all sessions'
                            events; averaged over tasks. Equals 0 when the
                            programmer never sees a model lottery outcome.
  visible near-misses       near-miss programs shown to the programmer.
  passive retries           regenerations the programmer triggers without
                            adding information (regenerate / paste-error).
  decision points           decisions handed to the programmer: typed holes to
                            fill (P1 handoff, P4) or clarifications to accept (P3).
  review items              information the programmer must read to proceed:
                            hidden-candidate disagreements (P2), diagnoses (P3).
  human line fraction       share of the final program's lines written in
                            human-owned holes (by the simulated programmer).
  spec soundness            share of model-written invariants that hold on the
                            hidden reference solution.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

from harness.metrics import binary_entropy, cluster_bootstrap, entropy_bits, wilson
from harness.store import JsonlStore

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
ORDER = ["slot_machine", "retry_budget", "hidden_best_of_n", "test_gated_reveal", "typed_holes_patch"]
LABELS = {"slot_machine": "Slot machine (baseline)", "retry_budget": "P1 Retry budget + handoff",
          "hidden_best_of_n": "P2 Hidden best-of-5", "test_gated_reveal": "P3 Test-gated reveal",
          "typed_holes_patch": "P4 Typed holes", "retry_budget_k1": "P1 Retry budget (k=1)",
          "retry_budget_k2": "P1 Retry budget (k=2)"}


def visible_signals(rec: dict) -> list[str]:
    out = []
    for e in rec["events"]:
        if e["kind"] in ("code", "best_of_n"):
            out.append(e["outcome"])
        elif e["kind"] == "revealed":
            out.append("pass")
        elif e["kind"] == "hidden_attempt":
            out.append("hidden")
    return out


def contested_tasks(results: Path = RESULTS) -> list[str]:
    """Tasks where at least one Phase 1 blind pull (vibe prompt) did not pass."""
    p = results / "summary" / "phase1_vibe.json"
    if not p.exists():
        return []
    per_task = json.loads(p.read_text())["per_task"]
    return sorted(t for t, v in per_task.items() if v["p_pass"] < 1)


def load_variant(name: str, results: Path = RESULTS) -> list[dict]:
    return JsonlStore(results / "phase2" / f"{name}.jsonl").load()


def summarize_variant(recs: list[dict], reps: int = 1000) -> dict:
    by_task = defaultdict(list)
    for r in recs:
        by_task[r["task_id"]].append(r)
    tasks = sorted(by_task)
    n = len(recs)

    def task_vis_entropy(tid):
        return entropy_bits(Counter(s for r in by_task[tid] for s in visible_signals(r)).values())

    def task_session_entropy(tid):
        rs = by_task[tid]
        return binary_entropy(sum(r["final_pass"] for r in rs) / len(rs))

    vis_events = [s for r in recs for s in visible_signals(r)]
    handoff = [r for r in recs if r["extra"].get("handoff")]
    inv_total = sum(r["invariants_total"] for r in recs)
    inv_valid = sum(r["invariants_valid_ref"] for r in recs)
    scaffolded = [r for r in recs if r["hole_compliant"] is not None]
    hints = [h for r in recs for h in r["extra"].get("hints_code_free", [])]
    k_pass = sum(r["final_pass"] for r in recs)

    def mean_pass(d):
        return [mean(r["final_pass"] for t in d for r in by_task[t])]

    out = {
        "n_sessions": n, "n_tasks": len(tasks),
        "final_pass_rate": k_pass / n, "final_pass_ci": wilson(k_pass, n),
        "final_pass_boot_ci": [x[0] for x in cluster_bootstrap(tasks, mean_pass, reps)],
        "model_only_pass_rate": mean(r["model_only_pass"] for r in recs),
        "visible_events_per_session": len(vis_events) / n,
        "pulls_per_session": mean(r["n_pulls"] for r in recs),
        "visible_entropy_bits": mean(task_vis_entropy(t) for t in tasks),
        "session_outcome_entropy_bits": mean(task_session_entropy(t) for t in tasks),
        "visible_near_misses_per_session": mean(r["visible_near_misses"] for r in recs),
        "visible_near_miss_share": (sum(s == "near_miss" for s in vis_events) / len(vis_events)) if vis_events else 0.0,
        "passive_retries_per_session": mean(r["passive_retries"] for r in recs),
        "decision_points_per_session": mean(r["decision_points"] for r in recs),
        "review_items_per_session": mean(r["review_items"] for r in recs),
        "human_line_frac": mean(r["human_line_frac"] for r in recs),
        "sessions_with_human_work": sum(r["decision_points"] > 0 for r in recs),
        "human_line_frac_when_engaged": (mean(r["human_line_frac"] for r in recs if r["decision_points"] > 0)
                                         if any(r["decision_points"] > 0 for r in recs) else None),
        "n_handoffs": len(handoff),
        "handoff_rescue_rate": mean(r["final_pass"] for r in handoff) if handoff else None,
        "invariants_total": inv_total, "invariants_valid_ref": inv_valid,
        "spec_soundness": inv_valid / inv_total if inv_total else None,
        "invariants_hold_final": sum(r["invariants_hold_final"] for r in recs),
        "hole_compliance": mean(r["hole_compliant"] for r in scaffolded) if scaffolded else None,
        "holes_per_scaffold": (mean(r["decision_points"] for r in scaffolded if r["hole_compliant"])
                               if any(r["hole_compliant"] for r in scaffolded) else None),
        "hint_code_free_rate": mean(hints) if hints else None, "n_hints": len(hints),
        "agent_calls_per_session": mean(r["agent_calls"] for r in recs),
        "agent_tokens_per_session": mean(r["agent_input_tokens"] + r["agent_output_tokens"] for r in recs),
        "agent_output_tokens_per_session": mean(r["agent_output_tokens"] for r in recs),
        "agent_cost_usd_per_session": mean(r["agent_cost_usd"] for r in recs),
        "agent_latency_s_mean": mean(r["agent_latency_s"] for r in recs),
        "agent_latency_s_median": median(r["agent_latency_s"] for r in recs),
        "proxy_calls_per_session": mean(r["proxy_calls"] for r in recs),
        "by_suite_pass": {s: mean(r["final_pass"] for r in recs if r["suite"] == s)
                          for s in ("humaneval", "mbpp", "original") if any(r["suite"] == s for r in recs)},
    }
    return out


def summarize(results: Path = RESULTS, reps: int = 1000) -> dict:
    d = results / "phase2"
    names = sorted(p.stem for p in d.glob("*.jsonl"))
    variants = {name: summarize_variant(load_variant(name, results), reps) for name in names
                if load_variant(name, results)}
    base = variants.get("slot_machine")
    if base:
        for name, v in variants.items():
            v["delta_vs_baseline"] = {
                key: ((v[key] - base[key]) / base[key] if base[key] else None)
                for key in ("visible_entropy_bits", "visible_near_misses_per_session",
                            "passive_retries_per_session", "agent_calls_per_session",
                            "agent_tokens_per_session", "agent_latency_s_mean")}
            v["pass_rate_change_pts"] = v["final_pass_rate"] - base["final_pass_rate"]
    contested = set(contested_tasks(results))
    for name, v in variants.items():
        con = [r for r in load_variant(name, results) if r["task_id"] in contested]
        v["contested_n_tasks"] = len({r["task_id"] for r in con})
        v["contested_pass_rate"] = mean(r["final_pass"] for r in con) if con else None
        v["contested_near_misses_per_session"] = mean(r["visible_near_misses"] for r in con) if con else None
        v["contested_decisions_per_session"] = mean(r["decision_points"] for r in con) if con else None
    meta_p = d / "meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    return {"meta": meta, "variants": variants, "order": [o for o in ORDER if o in variants],
            "labels": LABELS, "contested_tasks": sorted(contested)}


def main():
    s = summarize()
    out = RESULTS / "summary"
    out.mkdir(parents=True, exist_ok=True)
    (out / "phase2.json").write_text(json.dumps(s, indent=2))
    cols = ["n_sessions", "final_pass_rate", "visible_entropy_bits", "visible_near_misses_per_session",
            "passive_retries_per_session", "decision_points_per_session", "human_line_frac",
            "agent_calls_per_session", "agent_tokens_per_session", "agent_latency_s_mean"]
    print("variant".ljust(22) + "".join(c[:10].rjust(11) for c in cols))
    for name, v in s["variants"].items():
        print(name.ljust(22) + "".join(f"{v[c]:11.3f}" if isinstance(v[c], float) else f"{v[c]:11d}"
                                       for c in cols))


if __name__ == "__main__":
    main()
