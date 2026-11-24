"""Publication figures, generated only from results/summary/*.json and the raw logs.

    python -m analysis.plots      -> figures/fig{1,2,3}_*.pdf (+ .png previews)

Figure 3(b) needs results/summary/phase3.json (python -m analysis.phase3).
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from harness.store import JsonlStore  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SUMMARY = ROOT / "results" / "summary"
FIG = ROOT / "figures"

# Reference categorical palette (validated light-mode slots) + neutral ink.
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
GRAY, INK, INK2, GRID = "#b9b8b2", "#0b0b0b", "#52514e", "#e6e5e0"

plt.rcParams.update({
    "font.family": "serif", "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
    "mathtext.fontset": "stix", "font.size": 8.5, "axes.titlesize": 9, "axes.labelsize": 8.5,
    "xtick.labelsize": 7.5, "ytick.labelsize": 7.5, "legend.fontsize": 7.5,
    "axes.edgecolor": INK2, "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.linewidth": 0.6,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5, "axes.axisbelow": True,
    "legend.frameon": False, "pdf.fonttype": 42, "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
})

SHORT = {"he_": "", "mbpp_": "", "orig_": ""}


def short(tid: str) -> str:
    for p in SHORT:
        if tid.startswith(p):
            return tid[len(p):].replace("_", " ")
    return tid


def save(fig, name: str) -> None:
    FIG.mkdir(exist_ok=True)
    fig.savefig(FIG / f"{name}.pdf")
    fig.savefig(FIG / f"{name}.png", dpi=200)
    plt.close(fig)


def fig1(p1: dict, spec: dict | None) -> None:
    per = p1["per_task"]
    tids = sorted(per, key=lambda t: (per[t]["p_pass"], -per[t]["near_misses"], t))
    passes = np.array([per[t]["passes"] for t in tids])
    nms = np.array([per[t]["near_misses"] for t in tids])
    fails = np.array([per[t]["fails"] for t in tids])
    ent = np.array([per[t]["entropy_pass"] for t in tids])

    fig, (a, b) = plt.subplots(1, 2, figsize=(7.0, 2.25), gridspec_kw={"width_ratios": [2.3, 1]})
    y = np.arange(len(tids))
    h = 0.72
    a.barh(y, passes, h, color=BLUE, label="pass", edgecolor="white", linewidth=0.8)
    a.barh(y, nms, h, left=passes, color=ORANGE, label="near-miss", edgecolor="white", linewidth=0.8)
    a.barh(y, fails, h, left=passes + nms, color=GRAY, label="fail", edgecolor="white", linewidth=0.8)
    a.set_yticks(y, [short(t) for t in tids], fontsize=5.6)
    a.set_xlim(0, 10)
    a.set_xlabel("outcomes in 10 independent pulls (vibe prompt)")
    a.grid(axis="y", visible=False)
    a.tick_params(axis="y", length=0)
    ax2 = a.twiny()
    ax2.plot(ent, y, "o", ms=2.6, color=INK, label="entropy $H$")
    ax2.set_xlim(0, 1.05)
    ax2.set_xlabel("outcome entropy $H$ (bits)", fontsize=7.5, color=INK2)
    ax2.grid(False)
    ax2.spines["top"].set_visible(True)
    ax2.spines["top"].set_linewidth(0.4)
    ax2.tick_params(labelsize=6.5)
    h1, l1 = a.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    a.legend(h1 + h2, l1 + l2, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=4, fontsize=6.8,
             handlelength=1.0, columnspacing=1.2)
    a.set_title("(a) Per-task outcome mix", loc="left")

    blind = JsonlStore(ROOT / "results" / "phase1" / "vibe" / "blind.jsonl").load()
    fr = [r["frac"] for r in blind if r["outcome"] != "pass"]
    bins = np.linspace(0, 1, 11)
    b.hist(fr, bins=bins, color=ORANGE, edgecolor="white", linewidth=0.8)
    b.axvline(0.8, color=INK2, lw=0.8, ls="--")
    b.text(0.785, b.get_ylim()[1] * 0.92, "near-miss\nthreshold", ha="right", va="top", fontsize=6.5, color=INK2)
    b.set_xlabel("fraction of tests passed")
    b.set_ylabel("failed pulls")
    b.set_title("(b) How close failures come", loc="left")
    b.grid(axis="x", visible=False)
    save(fig, "fig1_variance_and_nearmiss")


def fig2(p1: dict) -> None:
    bc, ec = p1["blind_curve"], p1["error_paste_curve"]
    t = np.arange(1, len(bc["hazard"]) + 1)
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.0, 2.05))
    a.plot(t, bc["hazard"], "-o", color=BLUE, lw=2, ms=4.5, label="blind re-roll (Regime A)")
    a.fill_between(t, bc["hazard_ci_lo"], bc["hazard_ci_hi"], color=BLUE, alpha=0.15, lw=0)
    ok = [i for i, r in enumerate(ec["reached"]) if r > 0]
    te = t[ok]
    a.plot(te, [ec["hazard"][i] for i in ok], "-s", color=ORANGE, lw=2, ms=4.5, label="error-paste (Regime B)")
    a.fill_between(te, [ec["hazard_ci_lo"][i] for i in ok], [ec["hazard_ci_hi"][i] for i in ok],
                   color=ORANGE, alpha=0.15, lw=0)
    for i in ok:
        a.annotate(f"n={ec['reached'][i]}", (t[i], ec["hazard"][i]), textcoords="offset points",
                   xytext=(9, 5), ha="left", fontsize=6.3, color=INK2)
    a.set_xticks(t)
    a.set_ylim(0, 1.08)
    a.set_xlabel("attempt $t$")
    a.set_ylabel(r"$P(\mathrm{pass\ at\ } t \mid \mathrm{failed\ } 1..t{-}1)$")
    a.set_title("(a) Marginal retry curve", loc="left")
    a.legend(loc="center right", fontsize=6.8)
    b.plot(t, bc["cumulative"], "-o", color=BLUE, lw=2, ms=4.5, label="blind re-roll")
    b.plot(t, ec["cumulative"], "-s", color=ORANGE, lw=2, ms=4.5, label="error-paste")
    b.set_xticks(t)
    b.set_ylim(0.7, 1.01)
    b.set_xlabel("attempt budget $t$")
    b.set_ylabel("sessions passed within $t$")
    b.set_title("(b) Cumulative success", loc="left")
    b.legend(loc="lower right", fontsize=6.8)
    save(fig, "fig2_retry_curves")


def pareto_front(points):
    """Indices of points not dominated (higher x and higher y are better)."""
    out = []
    for i, (x, y) in enumerate(points):
        if not any((x2 >= x and y2 >= y) and (x2 > x or y2 > y) for j, (x2, y2) in enumerate(points) if j != i):
            out.append(i)
    return out


def _clustered_labels(ax, xs, ys, names, short_lab, offsets, tol=(0.03, 0.03)):
    """Label points, merging labels of points that (nearly) coincide."""
    xr = (max(xs) - min(xs)) or 1.0
    yr = (max(ys) - min(ys)) or 1.0
    groups: list[list[int]] = []
    for i in range(len(xs)):
        for g in groups:
            j = g[0]
            if abs(xs[i] - xs[j]) / xr < tol[0] and abs(ys[i] - ys[j]) / yr < tol[1]:
                g.append(i)
                break
        else:
            groups.append([i])
    for g in groups:
        lab = " = ".join(short_lab.get(names[i], names[i]) for i in g)
        off = offsets.get(names[g[0]], (6, -3))
        ax.annotate(lab, (xs[g[0]], ys[g[0]]), textcoords="offset points", xytext=off, fontsize=6.6,
                    color=INK, ha="left" if off[0] >= 0 else "right")


def fig3(p2: dict, p3: dict | None = None) -> None:
    V = p2["variants"]
    names = ["slot_machine", "retry_budget", "hidden_best_of_n", "retry_budget_k2", "retry_budget_k1",
             "test_gated_reveal", "typed_holes_patch"]
    names = [n for n in names if n in V]
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.0, 2.1), gridspec_kw={"width_ratios": [1, 1.25]})
    short_lab = {"slot_machine": "baseline", "retry_budget": "P1 k=3", "retry_budget_k1": "P1 k=1",
                 "retry_budget_k2": "P1 k=2", "hidden_best_of_n": "P2", "test_gated_reveal": "P3",
                 "typed_holes_patch": "P4"}
    base_nm = max(1e-9, V["slot_machine"]["visible_near_misses_per_session"])
    # (a) Phase 2, complete test feedback: agency vs success
    xs = [V[n]["decision_points_per_session"] for n in names]
    ys = [V[n]["final_pass_rate"] for n in names]
    front = sorted(pareto_front(list(zip(xs, ys))), key=lambda i: xs[i])
    a.plot([xs[i] for i in front], [ys[i] for i in front], color=INK2, lw=0.8, ls="--", zorder=1)
    for i, n in enumerate(names):
        a.scatter(xs[i], ys[i], s=10 + 38 * V[n]["visible_near_misses_per_session"] / base_nm,
                  color=INK if n == "slot_machine" else BLUE, edgecolor="white", linewidth=1.0, zorder=3)
    _clustered_labels(a, xs, ys, names, short_lab,
                      {"slot_machine": (5, 5), "retry_budget_k2": (1, -15), "test_gated_reveal": (6, 1),
                       "retry_budget_k1": (7, -4), "typed_holes_patch": (-6, 3)}, tol=(0.01, 0.01))
    a.set_xlim(-0.12, max(xs) * 1.08)
    a.set_ylim(min(ys) - 0.03, 1.015)
    a.set_xlabel("human decision points per session")
    a.set_ylabel("final pass rate")
    a.set_title("(a) Complete tests: success vs. engagement", loc="left")
    # (b) Phase 3, realistic feedback: where sessions end
    if not p3:
        b.axis("off")
        save(fig, "fig3_patch_tradeoffs")
        return
    W = p3["variants"]
    order = [n for n in p3["order"] if n in W][::-1]
    lab3 = {"slot_machine": "vibecoder", "attentive": "attentive", "retry_budget": "P1 k=1",
            "hidden_best_of_n": "P2", "test_gated_reveal": "P3", "typed_holes_patch": "P4",
            "typed_holes_fixed": "P4 + requests"}
    y = np.arange(len(order))
    ok = np.array([W[n]["intent_pass_rate"] for n in order])
    silent = np.array([W[n]["silent_failure_rate"] for n in order])
    other = 1 - ok - silent
    h = 0.62
    b.barh(y, ok, h, color=BLUE, label="intent pass", edgecolor="white", linewidth=0.8)
    b.barh(y, silent, h, left=ok, color=ORANGE, label="silent failure (looks done)", edgecolor="white",
           linewidth=0.8)
    b.barh(y, other, h, left=ok + silent, color=GRAY, label="visible failure", edgecolor="white", linewidth=0.8)
    lo = np.array([W[n]["intent_pass_boot_ci"][0] for n in order])
    hi = np.array([W[n]["intent_pass_boot_ci"][1] for n in order])
    b.errorbar(ok, y, xerr=[ok - lo, hi - ok], fmt="none", ecolor=INK, elinewidth=0.7, capsize=1.6, zorder=4)
    for yi, n in zip(y, order):
        b.text(1.02, yi, f"{W[n]['decision_points_per_session']:.2f}", va="center", ha="left", fontsize=6.6,
               color=INK2)
    b.text(1.02, len(order) - 0.35, "dec.", va="bottom", ha="left", fontsize=6.6, color=INK2)
    b.set_yticks(y, [lab3[n] for n in order])
    b.set_xlim(0, 1)
    b.set_ylim(-0.6, len(order) - 0.1)
    b.grid(axis="y", visible=False)
    b.set_xlabel("share of sessions")
    b.set_title(f"(b) Realistic feedback ({p3['meta'].get('n_visible', 3)} visible tests)", loc="left")
    b.legend(loc="upper center", bbox_to_anchor=(0.45, -0.2), ncol=3, fontsize=6.6, handlelength=1.2,
             columnspacing=1.0)
    save(fig, "fig3_patch_tradeoffs")


def main():
    p1 = json.loads((SUMMARY / "phase1_vibe.json").read_text())
    spec_p = SUMMARY / "phase1_spec.json"
    spec = json.loads(spec_p.read_text()) if spec_p.exists() else None
    fig1(p1, spec)
    fig2(p1)
    p2_p, p3_p = SUMMARY / "phase2.json", SUMMARY / "phase3.json"
    if p2_p.exists():
        fig3(json.loads(p2_p.read_text()), json.loads(p3_p.read_text()) if p3_p.exists() else None)
    print("figures written to", FIG)


if __name__ == "__main__":
    main()
