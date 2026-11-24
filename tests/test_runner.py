from harness.llm_client import LLMClient, ScriptedBackend
from harness.metrics import FAIL, NEAR_MISS, PASS, classify
from harness.runner import run_blind_unit, run_error_paste_unit
from harness.store import JsonlStore
from tasks import get_task

TASK = get_task("he_fix_spaces")
BUGGY = "```python\ndef fix_spaces(text):\n    return text.replace(' ', '_')\n```"
FIXED = "```python\n" + TASK.reference + "\n```"


def test_classify_boundaries():
    assert classify(10, 10) == PASS
    assert classify(9, 10) == NEAR_MISS
    assert classify(8, 10) == NEAR_MISS
    assert classify(7, 10) == FAIL
    assert classify(7, 8) == NEAR_MISS      # single failing test
    assert classify(5, 6) == NEAR_MISS
    assert classify(0, 10, syntax_ok=False) == FAIL
    assert classify(9, 10, syntax_ok=False) == FAIL


def test_error_paste_feeds_back_failures_and_stops_on_pass():
    seen = []

    def script(system, prompt, n):
        seen.append(prompt)
        return FIXED if "Please fix it" in prompt and prompt.count("[assistant]") >= 2 else BUGGY
    client = LLMClient(ScriptedBackend(script))
    recs = run_error_paste_unit(client, TASK, chain=0, max_turns=5)
    assert [r["turn"] for r in recs] == [1, 2, 3]
    assert recs[-1]["outcome"] == PASS and recs[0]["outcome"] != PASS
    assert "FAILED test_triple_run" in seen[1] and "got:" in seen[1]


def test_error_paste_turn1_shares_blind_draw():
    client = LLMClient(ScriptedBackend(lambda s, p, n: BUGGY if n == 0 else FIXED))
    b = run_blind_unit(client, TASK, 0)[0]
    e = run_error_paste_unit(client, TASK, 0, max_turns=1)[0]
    assert e["llm"]["key"] == b["llm"]["key"] and e["llm"]["cached"]
    assert e["code"] == b["code"]


def test_store_roundtrip(tmp_path):
    s = JsonlStore(tmp_path / "x.jsonl")
    s.append({"a": 1})
    s.append_many([{"a": 2}, {"a": 3}])
    assert [r["a"] for r in s.load()] == [1, 2, 3]
