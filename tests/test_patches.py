from harness.llm_client import LLMClient, ScriptedBackend
from harness.patches import (Ctx, behavioural_diff, hidden_best_of_n, is_code_free, retry_budget,
                             slot_machine, test_gated_reveal, typed_holes_patch)
from harness.prompts import SYSTEM_CODER, SYSTEM_DIAGNOSER, SYSTEM_HOLE_FILLER, SYSTEM_SCAFFOLDER
from tasks import get_task

TASK = get_task("he_fix_spaces")
BUGGY = "```python\ndef fix_spaces(text):\n    return text.replace(' ', '_')\n```"
FIXED = "```python\n" + TASK.reference + "\n```"
SKELETON = '''```python
import re

def fix_spaces(text: str) -> str:
    return re.sub(r" +", lambda m: hole_run(len(m.group(0))), text)

def hole_run(n: int) -> str:
    """Replacement for a run of n spaces."""
    raise NotImplementedError

def check_invariants():
    assert fix_spaces("a b") == "a_b"
    assert fix_spaces("a   b") == "a-b"
    assert fix_spaces("a  b") == "a-b"
```'''
GOOD_FILL = "```python\ndef hole_run(n):\n    return '-' if n > 2 else '_' * n\n```"
BAD_FILL = "```python\ndef hole_run(n):\n    return '_'\n```"


def script(fix_on_retry=True, fill_ok_round=1):
    def f(system, prompt, n):
        if system == SYSTEM_CODER:
            retry = "Please fix it" in prompt or "Clarifications:" in prompt
            return FIXED if (retry and fix_on_retry) else BUGGY
        if system == SYSTEM_DIAGNOSER:
            return "Runs of exactly two spaces stay as two underscores; only longer runs become a dash."
        if system == SYSTEM_SCAFFOLDER:
            return SKELETON
        if system == SYSTEM_HOLE_FILLER:
            return GOOD_FILL if ("Running the tests" in prompt or fill_ok_round == 1) else BAD_FILL
        raise AssertionError(system)
    return f


def ctx(**kw):
    return Ctx(LLMClient(ScriptedBackend(script(**kw))))


def test_slot_machine_shows_every_pull():
    s = slot_machine(ctx(), TASK, 0).to_dict()
    assert s["final_pass"] and s["pull_outcomes"] == ["fail", "pass"] and s["visible_near_misses"] == 0
    assert s["passive_retries"] == 1 and s["decision_points"] == 0


def test_retry_budget_hands_off_to_human():
    s = retry_budget(ctx(fix_on_retry=False), TASK, 0, k=2).to_dict()
    assert s["extra"]["handoff"] and s["n_pulls"] == 2
    assert s["decision_points"] == 1 and s["final_pass"] and not s["model_only_pass"]
    assert s["human_lines"] == 2 and 0 < s["human_line_frac"] < 1
    assert s["invariants_total"] == 3 and s["invariants_valid_ref"] == 2  # third invariant is wrong
    assert s["proxy_calls"] == 1 and s["agent_calls"] == 3


def test_retry_budget_no_handoff_when_model_succeeds():
    s = retry_budget(ctx(), TASK, 0, k=2).to_dict()
    assert s["final_pass"] and s["model_only_pass"] and "handoff" not in s["extra"]


def test_best_of_n_hides_candidates_and_diffs():
    s = hidden_best_of_n(ctx(), TASK, 0, n=5, rounds=2).to_dict()
    assert s["n_pulls"] == 2 and s["agent_calls"] == 10
    ev = s["events"][0]
    assert ev["kind"] == "best_of_n" and "distinct behaviours" in ev["diff"]


def test_behavioural_diff_reports_disagreements():
    from harness.runner import generate_and_test
    c = LLMClient(ScriptedBackend(lambda s, p, n: FIXED if n % 2 else BUGGY))
    cands = [generate_and_test(c, TASK, "p", i, "x") for i in range(4)]
    d = behavioural_diff(cands, 1, TASK)
    assert d["distinct"] == 2 and d["resolved"] and not d["unresolved"]


def test_test_gated_reveal_never_shows_failing_code():
    s = test_gated_reveal(ctx(), TASK, 0, k=2).to_dict()
    kinds = [e["kind"] for e in s["events"]]
    assert kinds == ["hidden_attempt", "diagnosis", "revealed"]
    assert s["n_pulls"] == 0 and s["visible_near_misses"] == 0 and s["final_pass"]
    assert s["decision_points"] == 1 and s["extra"]["hints_code_free"] == [True]


def test_typed_holes_iterates_on_holes_only():
    s = typed_holes_patch(ctx(fill_ok_round=2), TASK, 0, rounds=2).to_dict()
    fills = [e for e in s["events"] if e["kind"] == "human_fill"]
    assert [f["outcome"] for f in fills] == ["fail", "pass"]
    assert s["n_pulls"] == 0 and s["final_pass"] and s["hole_compliant"]
    assert s["invariants_hold_final"] == 2


def test_code_free_detector():
    assert is_code_free("Empty input should return an empty list.")
    assert not is_code_free("Use `def f(x): return x`")
    assert not is_code_free("```python\nx\n```")
