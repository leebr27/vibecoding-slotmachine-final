"""Outcome classification and reward-structure statistics."""
from __future__ import annotations

PASS, NEAR_MISS, FAIL = "pass", "near_miss", "fail"
NEAR_MISS_THRESHOLD = 0.8


def classify(n_pass: int, n_total: int, syntax_ok: bool = True) -> str:
    """Pass: all tests pass. Near-miss: syntactically valid and either >= 80% of
    tests pass or exactly one test fails. Fail: everything else, including
    syntax errors and crashes at import time (which score 0/T)."""
    if n_total > 0 and n_pass == n_total:
        return PASS
    if syntax_ok and n_total > 0 and n_pass > 0 and (
            n_pass / n_total >= NEAR_MISS_THRESHOLD or n_total - n_pass == 1):
        return NEAR_MISS
    return FAIL


# ---------------------------------------------------------------------------
# Reward-structure statistics
# ---------------------------------------------------------------------------
import math
import random
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Callable, Iterable, Sequence


def bernoulli_var(p: float) -> float:
    return p * (1.0 - p)


def entropy_bits(counts: Iterable[int]) -> float:
    """Shannon entropy (bits) of the empirical distribution given by counts."""
    counts = [c for c in counts if c > 0]
    n = sum(counts)
    if n == 0:
        return 0.0
    return -sum((c / n) * math.log2(c / n) for c in counts)


def binary_entropy(p: float) -> float:
    if p <= 0.0 or p >= 1.0:
        return 0.0
    return -(p * math.log2(p) + (1 - p) * math.log2(1 - p))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def per_task_outcomes(attempts: Sequence[dict]) -> dict[str, list[str]]:
    by = defaultdict(list)
    for a in sorted(attempts, key=lambda r: (r["task_id"], r["chain"], r["turn"])):
        by[a["task_id"]].append(a["outcome"])
    return dict(by)


def task_stats(outcomes: Sequence[str]) -> dict:
    c = Counter(outcomes)
    n = len(outcomes)
    k = c[PASS]
    p = k / n if n else 0.0
    fails = n - k
    return {
        "n": n, "passes": k, "near_misses": c[NEAR_MISS], "fails": c[FAIL], "p_pass": p,
        "bernoulli_var": bernoulli_var(p), "entropy_pass": binary_entropy(p),
        "entropy_3way": entropy_bits([c[PASS], c[NEAR_MISS], c[FAIL]]),
        "p_nm_given_failure": (c[NEAR_MISS] / fails) if fails else None,
    }


def blind_retry_curve(per_task: dict[str, list[str]], max_t: int = 5,
                      tasks: Sequence[str] | None = None) -> dict:
    """Marginal retry curve for independent re-rolls (Regime A).

    Pulls of the same prompt are i.i.d., so for task i with per-pull pass
    rate p_i (estimated by its empirical pass rate over N pulls):
        P(first t-1 pulls fail) = (1 - p_i)^(t-1).
    Pooling over tasks,
        hazard[t]     = sum_i (1-p_i)^(t-1) p_i / sum_i (1-p_i)^(t-1)
                      = P(pass at pull t | pulls 1..t-1 failed),
        cumulative[t] = 1 - mean_i (1-p_i)^t = P(some pass within t pulls).
    The pooled hazard decays because surviving sessions are increasingly
    concentrated on hard tasks (a selection effect), not because any single
    task's per-pull odds change."""
    tasks = list(tasks) if tasks is not None else list(per_task)
    ps = [sum(o == PASS for o in per_task[t]) / len(per_task[t]) for t in tasks]
    hazard, cumulative, reach = [], [], []
    for t in range(1, max_t + 1):
        r = [(1 - p) ** (t - 1) for p in ps]
        den = sum(r)
        hazard.append(sum(ri * p for ri, p in zip(r, ps)) / den if den > 0 else float("nan"))
        reach.append(den / len(ps))
        cumulative.append(1 - sum((1 - p) ** t for p in ps) / len(ps))
    return {"hazard": hazard, "cumulative": cumulative, "reach": reach}


def chains_by_task(attempts: Sequence[dict]) -> dict[str, list[list[dict]]]:
    by = defaultdict(lambda: defaultdict(list))
    for a in attempts:
        by[a["task_id"]][a["chain"]].append(a)
    return {tid: [sorted(ch, key=lambda r: r["turn"]) for _, ch in sorted(chs.items())]
            for tid, chs in by.items()}


def chain_retry_curve(chains: dict[str, list[list[dict]]], max_t: int = 5,
                      tasks: Sequence[str] | None = None) -> dict:
    """Empirical marginal retry curve for sequential (error-paste) chains."""
    tasks = list(tasks) if tasks is not None else list(chains)
    reached = [0] * max_t
    passed = [0] * max_t
    total = 0
    for tid in tasks:
        for ch in chains[tid]:
            total += 1
            for a in ch:
                t = a["turn"]
                if t <= max_t:
                    reached[t - 1] += 1
                    passed[t - 1] += a["outcome"] == PASS
    hazard = [passed[i] / reached[i] if reached[i] else float("nan") for i in range(max_t)]
    cum, acc = [], 0
    for i in range(max_t):
        acc += passed[i]
        cum.append(acc / total if total else 0.0)
    return {"hazard": hazard, "cumulative": cum, "reached": reached, "passed": passed, "n_chains": total}


def cluster_bootstrap(tasks: Sequence[str], stat: Callable[[list[str]], Sequence[float]],
                      reps: int = 2000, seed: int = 2520) -> tuple[list[float], list[float]]:
    """95% percentile CIs for a vector statistic, resampling tasks with replacement."""
    rng = random.Random(seed)
    tasks = list(tasks)
    samples = []
    for _ in range(reps):
        draw = [tasks[rng.randrange(len(tasks))] for _ in tasks]
        samples.append(list(stat(draw)))
    lo, hi = [], []
    for j in range(len(samples[0])):
        col = sorted(v for v in (s[j] for s in samples) if not math.isnan(v))
        if not col:
            lo.append(float("nan")); hi.append(float("nan")); continue
        lo.append(col[int(0.025 * (len(col) - 1))])
        hi.append(col[int(0.975 * (len(col) - 1))])
    return lo, hi


def transition_stats(chains: dict[str, list[list[dict]]]) -> dict:
    """Within error-paste chains: does a near-miss predict a pass next turn?
    Also counts regressions (fewer tests passing than the previous turn) and
    edit similarity between consecutive attempts."""
    nxt = {NEAR_MISS: [0, 0], FAIL: [0, 0]}
    regress = steps = 0
    sims = []
    for chs in chains.values():
        for ch in chs:
            for a, b in zip(ch, ch[1:]):
                steps += 1
                nxt[a["outcome"]][0] += 1
                nxt[a["outcome"]][1] += b["outcome"] == PASS
                regress += b["n_pass"] < a["n_pass"]
                sims.append(SequenceMatcher(None, a["code"], b["code"]).ratio())
    return {
        "p_pass_after_near_miss": nxt[NEAR_MISS][1] / nxt[NEAR_MISS][0] if nxt[NEAR_MISS][0] else None,
        "n_after_near_miss": nxt[NEAR_MISS][0],
        "p_pass_after_fail": nxt[FAIL][1] / nxt[FAIL][0] if nxt[FAIL][0] else None,
        "n_after_fail": nxt[FAIL][0],
        "regression_rate": regress / steps if steps else None,
        "n_steps": steps,
        "mean_consecutive_similarity": sum(sims) / len(sims) if sims else None,
    }


def pairwise_similarity(codes: Sequence[str]) -> float | None:
    sims = [SequenceMatcher(None, a, b).ratio() for i, a in enumerate(codes) for b in codes[i + 1:]]
    return sum(sims) / len(sims) if sims else None
