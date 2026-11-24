from analysis.phase1 import calibrate_k
from analysis.plots import pareto_front
from analysis.report_numbers import macro_name


def test_pareto_front():
    pts = [(0, 1.0), (0.3, 0.99), (2.0, 0.95), (0, 0.9), (1.0, 0.9)]
    assert pareto_front(pts) == [0, 1, 2]


def test_macro_names_are_letters_only():
    assert macro_name("blind haz 2") == "BlindHazTwo"
    assert macro_name("POneKOneRescue") == "POneKOneRescue"
    assert macro_name("pass humaneval").isalpha()


def test_calibrate_k_rule():
    assert calibrate_k([0.8, 0.4, 0.3, 0.1, 0.05]) == 3      # h(4)=0.1 < 0.4/2
    assert calibrate_k([0.8, 0.4, 0.1, 0.1, 0.1]) == 2       # h(3)=0.1 < 0.2
    assert calibrate_k([0.8, 0.9, 1.0, float("nan"), float("nan")]) == 3
    assert calibrate_k([0.8, 0.5, 0.5, 0.5, 0.5]) == 5


def test_paired_delta_and_points():
    from analysis.phase3 import paired_delta
    from analysis.report_numbers import pts
    base = [{"task_id": t, "intent_pass": p} for t, p in [("a", 0), ("a", 0), ("b", 1), ("b", 1)]]
    better = [{"task_id": t, "intent_pass": p} for t, p in [("a", 1), ("a", 1), ("b", 1), ("b", 1)]]
    d = paired_delta(better, base, reps=200)
    assert d["delta"] == 0.5 and d["n_tasks"] == 2 and 0 <= d["lo"] <= d["delta"] <= d["hi"] <= 1
    assert pts(0.234) == "$+$23" and pts(-0.05) == "$-$5" and pts(0.001) == "0"
