"""Emit report/numbers.tex (LaTeX macros), report/table_patches.tex and
report/table_realistic.tex from results/summary/*.json, so every number in the
paper is generated, not typed.

    python -m analysis.report_numbers
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "results" / "summary"
REPORT = ROOT / "report"


def pct(x, digits=0):
    return f"{100 * x:.{digits}f}\\%"


def f2(x):
    return f"{x:.2f}"


def pts(x):
    """Signed percentage-point difference for LaTeX, e.g. $+$23."""
    v = round(100 * x)
    if v == 0:
        return "0"
    return ("$+$" if v > 0 else "$-$") + str(abs(v))


def macro_name(key: str) -> str:
    # LaTeX macro names: letters only.
    words = re.split(r"[^A-Za-z0-9]+", key)
    digits = {"0": "Zero", "1": "One", "2": "Two", "3": "Three", "4": "Four", "5": "Five",
              "6": "Six", "7": "Seven", "8": "Eight", "9": "Nine"}
    out = "".join(w[:1].upper() + w[1:] for w in words if w)
    return "".join(digits.get(ch, ch) for ch in out)


def build() -> tuple[dict[str, str], str]:
    p1 = json.loads((SUMMARY / "phase1_vibe.json").read_text())
    sp = json.loads((SUMMARY / "phase1_spec.json").read_text())
    p2 = json.loads((SUMMARY / "phase2.json").read_text())
    calls = [json.loads(l) for l in (ROOT / "results" / "raw" / "llm_calls.jsonl").read_text().splitlines() if l]
    meta = json.loads((ROOT / "results" / "phase1" / "vibe" / "meta.json").read_text())
    m: dict[str, str] = {}

    # ---- setup
    m["model"] = calls[0]["model"].replace("_", "-")
    m["cliVersion"] = meta.get("claude_cli_version", "").split(" ")[0]
    m["nCalls"] = f"{len(calls):,}".replace(",", "{,}")
    m["totalCost"] = f"{sum(c['cost_usd'] for c in calls):.2f}"
    m["totalTokensM"] = f"{sum(c['input_tokens'] + c['cache_read_tokens'] + c['cache_creation_tokens'] + c['output_tokens'] for c in calls) / 1e6:.1f}"

    # ---- benchmark
    import sys
    sys.path.insert(0, str(ROOT))
    from tasks import load_tasks
    ts = load_tasks()
    m["nTests"] = str(sum(t.n_tests for t in ts))
    m["vibeWords"] = f"{sum(len(t.vibe_prompt.split()) for t in ts) / len(ts):.0f}"
    m["specWords"] = f"{sum(len(t.prompt.split()) for t in ts) / len(ts):.0f}"

    # ---- phase 1 (vibe)
    oc = p1["outcome_counts"]
    m["vibeN"] = str(p1["n_blind_attempts"])
    m["vibePass"] = str(oc["pass"])
    m["vibeNM"] = str(oc["near_miss"])
    m["vibeFail"] = str(oc["fail"])
    m["vibePassRate"] = pct(p1["pass_rate"])
    m["vibePassLo"], m["vibePassHi"] = pct(p1["pass_rate_ci"][0]), pct(p1["pass_rate_ci"][1])
    m["nmGivenFail"] = pct(p1["p_nm_given_failure"])
    m["nmGivenFailLo"], m["nmGivenFailHi"] = pct(p1["p_nm_given_failure_ci"][0]), pct(p1["p_nm_given_failure_ci"][1])
    m["meanEntropy"] = f2(p1["mean_entropy_bits"])
    m["meanVar"] = f"{p1['mean_bernoulli_var']:.3f}"
    m["nStochastic"] = str(p1["n_tasks_stochastic"])
    m["nAlwaysPass"] = str(p1["n_tasks_always_pass"])
    m["nNeverPass"] = str(p1["n_tasks_never_pass"])
    m["nWithNM"] = str(p1["n_tasks_with_near_miss"])
    m["meanFracFailures"] = pct(p1["mean_frac_tests_passed_in_failures"])
    m["medianFracFailures"] = pct(p1["median_frac_tests_passed_in_failures"])
    m["distinctBehaviours"] = f"{p1['mean_distinct_behaviours_per_task']:.2f}"
    m["codeSimilarity"] = f2(p1["mean_pairwise_code_similarity_blind"])
    stoch = {t: v for t, v in p1["per_task"].items() if 0 < v["passes"] < v["n"]}
    m["stochEntropy"] = f2(sum(v["entropy_pass"] for v in stoch.values()) / len(stoch)) if stoch else "0"
    for s, v in p1["by_suite"].items():
        m[f"pass {s}"] = pct(v["pass_rate"])
        m[f"stoch {s}"] = str(v["n_stochastic"])
    bc, ec = p1["blind_curve"], p1["error_paste_curve"]
    for i in range(5):
        m[f"blind haz {i + 1}"] = pct(bc["hazard"][i])
        m[f"blind cum {i + 1}"] = pct(bc["cumulative"][i])
    m["blindHazTwoLo"], m["blindHazTwoHi"] = pct(bc["hazard_ci_lo"][1]), pct(bc["hazard_ci_hi"][1])
    for i, (h, r) in enumerate(zip(ec["hazard"], ec["reached"])):
        m[f"ep reached {i + 1}"] = str(r)
        if r:
            m[f"ep haz {i + 1}"] = pct(h)
        m[f"ep cum {i + 1}"] = pct(ec["cumulative"][i])
    tr = p1["error_paste_transitions"]
    m["passAfterNM"] = pct(tr["p_pass_after_near_miss"])
    m["nAfterNM"] = str(tr["n_after_near_miss"])
    m["passAfterFail"] = pct(tr["p_pass_after_fail"])
    m["nAfterFail"] = str(tr["n_after_fail"])
    m["regressionRate"] = pct(tr["regression_rate"])
    m["consecSimilarity"] = f2(tr["mean_consecutive_similarity"])
    es = p1["error_paste_sessions"]
    m["epMeanTurns"] = f2(es["mean_turns"])
    m["epFinalPass"] = pct(es["final_pass_rate"])
    m["kStar"] = str(p1["k_star"])
    # spec control
    m["specPassRate"] = pct(sp["pass_rate"])
    m["specN"] = str(sp["n_blind_attempts"])
    m["specEntropy"] = f2(sp["mean_entropy_bits"])
    # recurring failing test
    from collections import Counter
    blind = [json.loads(l) for l in (ROOT / "results" / "phase1" / "vibe" / "blind.jsonl").read_text().splitlines()]
    fails = [r for r in blind if r["outcome"] != "pass"]
    sig = Counter((r["task_id"], tuple(r["failed_tests"])) for r in fails)
    modal_by_task = {}
    for (tid, ft), c in sig.items():
        modal_by_task[tid] = max(modal_by_task.get(tid, 0), c)
    nf_by_task = Counter(r["task_id"] for r in fails)
    m["modalSignatureShare"] = pct(sum(modal_by_task.values()) / len(fails))
    m["nFailedPulls"] = str(len(fails))

    # ---- phase 2
    V = p2["variants"]
    base = V["slot_machine"]
    key = {"slot_machine": "Base", "retry_budget": "POne", "hidden_best_of_n": "PTwo",
           "test_gated_reveal": "PThree", "typed_holes_patch": "PFour", "retry_budget_k1": "POneKOne",
           "retry_budget_k2": "POneKTwo"}
    for name, v in V.items():
        k = key.get(name)
        if not k:
            continue
        m[f"{k}Pass"] = pct(v["final_pass_rate"])
        m[f"{k}PassLo"], m[f"{k}PassHi"] = pct(v["final_pass_boot_ci"][0]), pct(v["final_pass_boot_ci"][1])
        m[f"{k}ModelPass"] = pct(v["model_only_pass_rate"])
        m[f"{k}N"] = str(v["n_sessions"])
        m[f"{k}VisH"] = f2(v["visible_entropy_bits"])
        m[f"{k}NM"] = f2(v["visible_near_misses_per_session"])
        m[f"{k}Retries"] = f2(v["passive_retries_per_session"])
        m[f"{k}Decisions"] = f2(v["decision_points_per_session"])
        m[f"{k}Review"] = f2(v["review_items_per_session"])
        m[f"{k}HumanFrac"] = pct(v["human_line_frac"])
        m[f"{k}Calls"] = f"{v['agent_calls_per_session']:.1f}"
        m[f"{k}TokK"] = f"{v['agent_tokens_per_session'] / 1000:.1f}"
        m[f"{k}Lat"] = f"{v['agent_latency_s_mean']:.1f}"
        m[f"{k}Handoffs"] = str(v["n_handoffs"])
        if v["handoff_rescue_rate"] is not None:
            m[f"{k}Rescue"] = pct(v["handoff_rescue_rate"])
        if v["human_line_frac_when_engaged"] is not None:
            m[f"{k}HumanFracEngaged"] = pct(v["human_line_frac_when_engaged"])
        m[f"{k}Engaged"] = str(v["sessions_with_human_work"])
        if v["spec_soundness"] is not None:
            m[f"{k}Soundness"] = pct(v["spec_soundness"])
            m[f"{k}InvTotal"] = str(v["invariants_total"])
        if v["hole_compliance"] is not None:
            m[f"{k}Compliance"] = pct(v["hole_compliance"])
        if v["holes_per_scaffold"] is not None:
            m[f"{k}Holes"] = f"{v['holes_per_scaffold']:.1f}"
        if v["hint_code_free_rate"] is not None:
            m[f"{k}CodeFree"] = pct(v["hint_code_free_rate"])
            m[f"{k}NHints"] = str(v["n_hints"])
        for s, val in v["by_suite_pass"].items():
            m[f"{k} pass {s}"] = pct(val)
        d = v.get("delta_vs_baseline", {})
        if d.get("visible_entropy_bits") is not None:
            m[f"{k}VisHRed"] = pct(-d["visible_entropy_bits"])
        if d.get("visible_near_misses_per_session") is not None:
            m[f"{k}NMRed"] = pct(-d["visible_near_misses_per_session"])
        if d.get("passive_retries_per_session") is not None:
            m[f"{k}RetryRed"] = pct(-d["passive_retries_per_session"])
        if d.get("agent_tokens_per_session") is not None:
            m[f"{k}TokX"] = f"{v['agent_tokens_per_session'] / base['agent_tokens_per_session']:.1f}"

    # ---- P4 failure anatomy
    p4 = [json.loads(l) for l in (ROOT / "results" / "phase2" / "typed_holes_patch.jsonl").read_text().splitlines() if l]
    p4f = [r for r in p4 if not r["final_pass"]]
    last = [[e for e in r["events"] if e["kind"] == "human_fill"][-1] for r in p4f]
    m["pFourFailures"] = str(len(p4f))
    m["pFourSingleFail"] = str(sum(e["n_total"] - e["n_pass"] == 1 for e in last))

    # ---- phase 2 on contested tasks (at least one failed Phase 1 pull)
    m["nContested"] = str(len(p2.get("contested_tasks", [])))
    for name, v in V.items():
        k = key.get(name)
        if k and v.get("contested_pass_rate") is not None:
            m[f"{k}ContestedPass"] = pct(v["contested_pass_rate"])
            m[f"{k}ContestedNM"] = f2(v["contested_near_misses_per_session"])
            m[f"{k}ContestedDecisions"] = f2(v["contested_decisions_per_session"])

    # ---- phase 3 (realistic feedback)
    table3 = ""
    p3_path = SUMMARY / "phase3.json"
    if p3_path.exists():
        p3 = json.loads(p3_path.read_text())
        W = p3["variants"]
        m["nVisible"] = str(p3["meta"].get("n_visible", 3))
        m["nHeldOut"] = str(sum(t.n_tests for t in ts) - int(m["nVisible"]) * len(ts))
        key3 = {"slot_machine": "RVibe", "attentive": "RAtt", "retry_budget": "ROne", "hidden_best_of_n": "RTwo",
                "test_gated_reveal": "RThree", "typed_holes_patch": "RFour", "typed_holes_fixed": "RFourPlus"}
        for name, v in W.items():
            k = key3[name]
            m[f"{k}Pass"] = pct(v["intent_pass_rate"])
            m[f"{k}PassLo"], m[f"{k}PassHi"] = pct(v["intent_pass_boot_ci"][0]), pct(v["intent_pass_boot_ci"][1])
            m[f"{k}N"] = str(v["n_sessions"])
            m[f"{k}VisPass"] = pct(v["visible_pass_rate"])
            m[f"{k}Silent"] = pct(v["silent_failure_rate"])
            if v["silent_given_visible_pass"] is not None:
                m[f"{k}SilentGivenVis"] = pct(v["silent_given_visible_pass"])
            m[f"{k}NM"] = f2(v["visible_near_misses_per_session"])
            m[f"{k}Decisions"] = f2(v["decision_points_per_session"])
            m[f"{k}Turns"] = f2(v["human_turns_per_session"])
            m[f"{k}Shown"] = f"{v['shown_lines_per_session']:.0f}"
            m[f"{k}HumanFrac"] = pct(v["human_line_frac"])
            m[f"{k}Calls"] = f"{v['agent_calls_per_session']:.1f}"
            m[f"{k}TokK"] = f"{v['agent_tokens_per_session'] / 1000:.1f}"
            m[f"{k}TokX"] = f"{v['token_ratio_vs_vibecoder']:.1f}"
            m[f"{k}Lat"] = f"{v['agent_latency_s_mean']:.1f}"
            m[f"{k}Clar"] = f2(v["clarifications_per_session"])
            if v.get("contested_intent_pass_rate") is not None:
                m[f"{k}ContestedPass"] = pct(v["contested_intent_pass_rate"])
                m[f"{k}ContestedSilent"] = pct(v["contested_silent_failure_rate"])
            for dkey, tag in (("delta_intent_vs_vibecoder", "Delta"), ("contested_delta_intent", "ContestedDelta"),
                              ("delta_silent_vs_vibecoder", "SilentDelta")):
                d = v.get(dkey) or {}
                if d.get("delta") is not None:
                    m[f"{k}{tag}"] = pts(d["delta"])
                    m[f"{k}{tag}Lo"], m[f"{k}{tag}Hi"] = pts(d["lo"]), pts(d["hi"])
            for s_, val in v["by_suite_pass"].items():
                m[f"{k} pass {s_}"] = pct(val)
            if v["diagnoses_accepted_rate"] is not None:
                m[f"{k}DiagAccepted"] = pct(v["diagnoses_accepted_rate"])
                m[f"{k}DiagReviewed"] = str(v["diagnoses_reviewed"])
            if v["n_hole_requests"]:
                m[f"{k}Requests"] = str(v["n_hole_requests"])
                m[f"{k}RequestPass"] = pct(v["hole_request_pass_rate"])
            if v["n_handoffs"]:
                m[f"{k}Handoffs"] = str(v["n_handoffs"])
        p3dir = ROOT / "results" / "phase3"
        vib = [json.loads(l) for l in (p3dir / "slot_machine.jsonl").read_text().splitlines() if l]
        m["rVisFailFirst"] = str(sum(r["events"][0]["outcome"] != "pass" for r in vib))
        att = [json.loads(l) for l in (p3dir / "attentive.jsonl").read_text().splitlines() if l]
        first_reviews = [[e for e in r["events"] if e["kind"] == "review"][0]["accepted"] for r in att]
        m["rAttAcceptFirst"] = pct(sum(first_reviews) / len(first_reviews))
        clar = [c for r in att for c in r["extra"].get("clarifications", [])]
        m["rAttClarWords"] = f"{sum(len(c.split()) for c in clar) / len(clar):.0f}" if clar else "0"
        m["rSilentTasks"] = str(len({r["task_id"] for r in vib if r["silent_failure"]}))
        from analysis.phase3 import load as load3, paired_delta
        if load3("typed_holes_fixed") and load3("typed_holes_patch"):
            d = paired_delta(load3("typed_holes_fixed"), load3("typed_holes_patch"), "intent_pass", 2000)
            m["rFourPlusVsFour"], m["rFourPlusVsFourLo"], m["rFourPlusVsFourHi"] = pts(d["delta"]), pts(d["lo"]), pts(d["hi"])
        label3 = {"slot_machine": "Vibecoder (paste errors)", "attentive": "Attentive programmer",
                  "retry_budget": "P1 retry budget, $k{=}1$", "hidden_best_of_n": "P2 hidden best-of-5",
                  "test_gated_reveal": "P3 test-gated reveal", "typed_holes_patch": "P4 typed holes",
                  "typed_holes_fixed": "P4 + hole requests"}
        rows3 = []
        for name in p3["order"]:
            v = W[name]
            d = v.get("delta_intent_vs_vibecoder") or {}
            delta = "--" if name == "slot_machine" else f"{pts(d['delta'])} [{pts(d['lo'])}, {pts(d['hi'])}]"
            lo, hi = v["intent_pass_boot_ci"]
            rows3.append(" & ".join([
                label3[name], f"{pct(v['intent_pass_rate'])} [{pct(lo)}, {pct(hi)}]",
                delta, pct(v["silent_failure_rate"]), f2(v["visible_near_misses_per_session"]),
                f2(v["decision_points_per_session"]), f2(v["human_turns_per_session"]),
                f"{v['agent_tokens_per_session'] / 1000:.1f}"]) + r" \\")
            if name == "attentive":
                rows3.append(r"\addlinespace[2pt]")
        table3 = "\n".join([
            r"\begin{tabular}{@{}lrrrrrrr@{}}", r"\toprule",
            r"Condition & Intent pass [95\% CI] & $\Delta$ pts [95\% CI] & Silent & NM & Dec. & Turns & kTok \\",
            r"\midrule", *rows3, r"\bottomrule", r"\end{tabular}"])

    # ---- table
    rows = []
    order = ["slot_machine", "retry_budget_k1", "retry_budget_k2", "retry_budget", "hidden_best_of_n",
             "test_gated_reveal", "typed_holes_patch"]
    label = {"slot_machine": "Slot machine (baseline)", "retry_budget": "P1 retry budget, $k{=}3$",
             "retry_budget_k1": "P1 retry budget, $k{=}1$", "retry_budget_k2": "P1 retry budget, $k{=}2$",
             "hidden_best_of_n": "P2 hidden best-of-5", "test_gated_reveal": "P3 test-gated reveal",
             "typed_holes_patch": "P4 typed holes"}
    for name in order:
        if name not in V:
            continue
        v = V[name]
        sound = pct(v["spec_soundness"]) if v["spec_soundness"] is not None else "--"
        rows.append(" & ".join([
            label[name], pct(v["final_pass_rate"]), f2(v["visible_entropy_bits"]),
            f2(v["visible_near_misses_per_session"]), f2(v["passive_retries_per_session"]),
            f2(v["decision_points_per_session"]), pct(v["human_line_frac"]), sound,
            f"{v['agent_calls_per_session']:.1f}", f"{v['agent_tokens_per_session'] / 1000:.1f}",
            f"{v['agent_latency_s_mean']:.1f}"]) + r" \\")
        if name in ("slot_machine", "retry_budget"):
            rows.append(r"\addlinespace[2pt]")
    table = "\n".join([
        r"\begin{tabular}{@{}lrrrrrrrrrr@{}}", r"\toprule",
        r"Condition & Pass & H & NM & Ret. & Dec. & Hum. & Sound & Calls & kTok & Lat. \\", r"\midrule",
        *rows, r"\bottomrule", r"\end{tabular}"])
    return m, table, table3


def main():
    m, table, table3 = build()
    REPORT.mkdir(exist_ok=True)
    lines = ["% Generated by analysis/report_numbers.py from results/summary/*.json. Do not edit."]
    for k, v in m.items():
        lines.append(f"\\newcommand{{\\{macro_name(k)}}}{{{v}}}")
    (REPORT / "numbers.tex").write_text("\n".join(lines) + "\n")
    (REPORT / "table_patches.tex").write_text("% Generated by analysis/report_numbers.py. Do not edit.\n" + table + "\n")
    if table3:
        (REPORT / "table_realistic.tex").write_text("% Generated by analysis/report_numbers.py. Do not edit.\n"
                                                    + table3 + "\n")
    print(f"{len(m)} macros -> report/numbers.tex")


if __name__ == "__main__":
    main()
