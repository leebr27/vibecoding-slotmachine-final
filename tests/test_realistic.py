"""Phase 3 protocols: visible-test feedback, held-out scoring, a programmer who knows the intent."""
from harness.llm_client import LLMClient, ScriptedBackend
from harness.patches import Ctx
from harness.prompts import SYSTEM_CODER, SYSTEM_DIAGNOSER, SYSTEM_PROGRAMMER, SYSTEM_SCAFFOLDER
from harness.realistic import (N_VISIBLE, attentive, check, clip_words, hidden_best_of_n, is_accept,
                               parse_hole_request, retry_budget, slot_machine, test_gated_reveal, typed_holes,
                               visible_task)
from tasks import get_task

TASK = get_task("he_fix_spaces")
# Passes the programmer's three visible tests (no / one / leading space) but not the full intent.
LOOKS_DONE = "```python\ndef fix_spaces(text):\n    return text.replace(' ', '_')\n```"
VISIBLY_BROKEN = "```python\ndef fix_spaces(text):\n    return text\n```"
CORRECT = "```python\n" + TASK.reference + "\n```"
GOOD_SKELETON = '''```python
import re

def fix_spaces(text: str) -> str:
    return re.sub(r" +", lambda m: hole_run(len(m.group(0))), text)

def hole_run(n: int) -> str:
    """Replacement for a run of n spaces."""
    raise NotImplementedError

def check_invariants():
    assert fix_spaces("a b") == "a_b"
```'''
# The key decision (what counts as a long run) is fixed outside the hole.
BAD_SKELETON = '''```python
import re

def fix_spaces(text: str) -> str:
    text = re.sub(r" {2,}", "-", text)
    return hole_single(text)

def hole_single(text: str) -> str:
    """Replace the remaining single spaces."""
    raise NotImplementedError
```'''
GOOD_FILL = "```python\ndef hole_run(n):\n    return '-' if n > 2 else '_' * n\n```"
SINGLE_FILL = "```python\ndef hole_single(text):\n    return text.replace(' ', '_')\n```"
CLAR = "Runs of more than two spaces become one dash; exactly two spaces stay as two underscores."


def coder(system, prompt):
    if "more than two" in prompt or "two underscores" in prompt:
        return CORRECT
    return None


def make(coder_default=LOOKS_DONE, scaffold=GOOD_SKELETON, request=False, diagnosis="Use dashes."):
    def f(system, prompt, n):
        if system == SYSTEM_CODER:
            return coder(system, prompt) or (CORRECT if "Please fix it" in prompt and coder_default == VISIBLY_BROKEN
                                             else coder_default)
        if system == SYSTEM_DIAGNOSER:
            return diagnosis
        if system == SYSTEM_SCAFFOLDER:
            return GOOD_SKELETON if "asked for this decision" in prompt else scaffold
        if system == SYSTEM_PROGRAMMER:
            if "The assistant replied with this code" in prompt:
                return "ACCEPT" if TASK.reference.strip() in prompt else CLAR
            if "suggests adding this clarification" in prompt:
                return CLAR
            if "REQUEST_HOLE" in prompt and request:
                return "REQUEST_HOLE: How many consecutive spaces count as a long run."
            return SINGLE_FILL if "hole_single" in prompt else GOOD_FILL
        raise AssertionError(system)
    return Ctx(LLMClient(ScriptedBackend(f)))


def test_visible_task_is_first_three_tests():
    vis = visible_task(TASK)
    assert [t.name for t in vis.tests] == [t.name for t in TASK.tests[:N_VISIBLE]]
    chk = check(TASK, "def fix_spaces(text):\n    return text.replace(' ', '_')\n")
    assert chk.vis_pass and not chk.full_pass


def test_vibecoder_ships_code_that_only_looks_done():
    s = slot_machine(make(), TASK, 0).to_dict()
    assert s["visible_pass"] and not s["intent_pass"] and s["silent_failure"]
    assert s["n_pulls"] == 1 and s["human_turns"] == 0 and s["decision_points"] == 0
    assert s["events"][0]["outcome"] == "pass" and s["events"][0]["intent_outcome"] != "pass"


def test_vibecoder_pastes_visible_failures():
    s = slot_machine(make(coder_default=VISIBLY_BROKEN), TASK, 0).to_dict()
    assert [e["outcome"] for e in s["events"]] == ["fail", "pass"]
    assert s["intent_pass"] and s["human_turns"] == 1 and s["passive_retries"] == 1


def test_attentive_programmer_supplies_the_missing_detail():
    s = attentive(make(), TASK, 0).to_dict()
    assert s["intent_pass"] and not s["silent_failure"]
    assert s["decision_points"] == 1 and s["proxy_calls"] == 2 and s["extra"]["clarifications"] == [CLAR]


def test_typed_holes_with_intent():
    s = typed_holes(make(), TASK, 0, rounds=3).to_dict()
    assert s["intent_pass"] and s["decision_points"] == 1 and s["n_pulls"] == 0


def test_typed_holes_fails_when_decision_is_in_boilerplate():
    s = typed_holes(make(scaffold=BAD_SKELETON), TASK, 0, rounds=3).to_dict()
    assert s["visible_pass"] and not s["intent_pass"]


def test_hole_request_rescaffolds_the_buried_decision():
    s = typed_holes(make(scaffold=BAD_SKELETON, request=True), TASK, 0, rounds=3, requests=True).to_dict()
    kinds = [e["kind"] for e in s["events"]]
    assert kinds[:3] == ["scaffold", "hole_request", "scaffold"] and s["events"][2]["rescaffold"]
    assert s["intent_pass"] and s["decision_points"] == 2 and "hole_request" in s["extra"]


def test_gated_reveal_programmer_corrects_the_diagnosis():
    s = test_gated_reveal(make(coder_default=VISIBLY_BROKEN), TASK, 0, k=3).to_dict()
    kinds = [e["kind"] for e in s["events"]]
    assert kinds == ["hidden_attempt", "diagnosis", "diagnosis_review", "revealed"]
    assert s["extra"]["diagnoses_accepted"] == [False] and s["extra"]["clarifications"] == [clip_words(CLAR)]
    assert s["intent_pass"] and s["visible_near_misses"] == 0


def test_best_of_n_ranks_by_visible_tests_only():
    s = hidden_best_of_n(make(), TASK, 0, n=5, rounds=3).to_dict()
    assert s["n_pulls"] == 1 and s["silent_failure"]
    assert s["events"][0]["hidden_intent_outcomes"] and s["agent_calls"] == 5


def test_retry_budget_hands_off_only_on_visible_failure():
    s = retry_budget(make(), TASK, 0, k=1).to_dict()
    assert "handoff" not in s["extra"] and s["silent_failure"]
    s = retry_budget(make(coder_default=VISIBLY_BROKEN), TASK, 0, k=1).to_dict()
    assert s["extra"]["handoff"] and s["intent_pass"] and s["decision_points"] == 1


def test_reply_parsers():
    assert is_accept("ACCEPT") and is_accept("Accept.") and not is_accept("Accept runs of two as dashes")
    assert parse_hole_request("REQUEST_HOLE: the run length threshold") == "the run length threshold"
    assert parse_hole_request("```python\nREQUEST_HOLE: x\n```") is None
    assert len(clip_words("word " * 100).split()) == 40
