import math

from harness.metrics import (FAIL, NEAR_MISS, PASS, binary_entropy,
                             blind_retry_curve, chain_retry_curve, cluster_bootstrap,
                             entropy_bits, task_stats, transition_stats, wilson)


def test_entropy_and_variance():
    assert binary_entropy(0.5) == 1.0 and binary_entropy(0) == 0 and binary_entropy(1) == 0
    assert math.isclose(entropy_bits([1, 1, 1, 1]), 2.0)
    s = task_stats([PASS] * 5 + [NEAR_MISS] * 3 + [FAIL] * 2)
    assert s["p_pass"] == 0.5 and s["bernoulli_var"] == 0.25 and s["entropy_pass"] == 1.0
    assert math.isclose(s["p_nm_given_failure"], 0.6)


def test_blind_curve_selection_effect():
    # One always-pass task and one 10% task: pooled hazard must fall after t=1.
    per = {"easy": [PASS] * 10, "hard": [PASS] + [FAIL] * 9}
    c = blind_retry_curve(per, max_t=3)
    assert math.isclose(c["hazard"][0], 0.55)
    assert math.isclose(c["hazard"][1], 0.1)  # only the hard task can reach t=2
    assert math.isclose(c["cumulative"][1], 1 - 0.81 / 2)
    assert c["cumulative"][0] < c["cumulative"][1] < c["cumulative"][2] <= 1


def _a(tid, chain, turn, outcome, n_pass, code="x"):
    return {"task_id": tid, "chain": chain, "turn": turn, "outcome": outcome, "n_pass": n_pass, "code": code}


def test_chain_curve_and_transitions():
    chains = {"t": [[_a("t", 0, 1, NEAR_MISS, 9), _a("t", 0, 2, PASS, 10)],
                    [_a("t", 1, 1, FAIL, 5), _a("t", 1, 2, FAIL, 3), _a("t", 1, 3, PASS, 10)],
                    [_a("t", 2, 1, PASS, 10)]]}
    c = chain_retry_curve(chains, max_t=3)
    assert c["reached"] == [3, 2, 1] and c["passed"] == [1, 1, 1]
    assert c["hazard"] == [1 / 3, 0.5, 1.0] and math.isclose(c["cumulative"][2], 1.0)
    tr = transition_stats(chains)
    assert tr["p_pass_after_near_miss"] == 1.0 and tr["p_pass_after_fail"] == 0.5
    assert math.isclose(tr["regression_rate"], 1 / 3)


def test_wilson_and_bootstrap():
    lo, hi = wilson(5, 10)
    assert lo < 0.5 < hi
    lo, hi = cluster_bootstrap(["a", "b", "c"], lambda d: [len(d)], reps=50)
    assert lo == [3] and hi == [3]
