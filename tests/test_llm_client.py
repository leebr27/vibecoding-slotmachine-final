import json
import os

import pytest

from harness.codeutil import code_lines, extract_code, parses
from harness.llm_client import (LLMClient, LLMError, ScriptedBackend, find_claude_binary,
                                make_backend)


def echo_script(system, prompt, n):
    return f"```python\nx = {n}\n```"


def test_cache_hit_and_samples(tmp_path):
    be = ScriptedBackend(echo_script)
    c = LLMClient(be, tmp_path / "calls.jsonl")
    a = c.complete("p", "sys", sample=0)
    b = c.complete("p", "sys", sample=0)
    d = c.complete("p", "sys", sample=1)
    assert a.text == b.text and b.cached and not a.cached
    assert d.text != a.text
    assert be.n_calls == 2


def test_resume_from_log(tmp_path):
    log = tmp_path / "calls.jsonl"
    c1 = LLMClient(ScriptedBackend(echo_script), log)
    r1 = c1.complete("p", "sys", sample=3, tag="blind")
    with log.open("a") as f:
        f.write('{"torn": ')  # simulate interruption mid-write
    be2 = ScriptedBackend(echo_script)
    c2 = LLMClient(be2, log)
    r2 = c2.complete("p", "sys", sample=3)
    assert r2.cached and r2.text == r1.text and be2.n_calls == 0
    rec = json.loads(log.read_text().splitlines()[0])
    assert rec["tag"] == "blind" and rec["prompt"] == "p" and rec["system"] == "sys"


def test_key_depends_on_everything():
    c = LLMClient(ScriptedBackend(echo_script))
    k = c.request_key("s", "p", 0)
    assert k != c.request_key("s2", "p", 0)
    assert k != c.request_key("s", "p2", 0)
    assert k != c.request_key("s", "p", 1)


def test_retries_then_gives_up(monkeypatch):
    import harness.llm_client as m
    monkeypatch.setattr(m.time, "sleep", lambda s: None)

    def boom(system, prompt, n):
        raise LLMError("nope")
    c = LLMClient(ScriptedBackend(boom), max_retries=2)
    with pytest.raises(LLMError):
        c.complete("p", "s")


def test_extract_code_variants():
    assert extract_code("Here:\n```python\ndef f():\n    return 1\n```\nDone") == "def f():\n    return 1\n"
    assert "def g" in extract_code("```\ndef g(): pass\n```")
    two = extract_code("```python\nimport re\n```\ntext\n```python\nx = 1\n```")
    assert "import re" in two and "x = 1" in two
    assert extract_code("def h(): return 2") == "def h(): return 2\n"
    assert parses("x = 1") and not parses("def (")
    assert code_lines("# c\n\nx = 1\ny = 2\n") == 2


@pytest.mark.skipif(not os.environ.get("VSM_LIVE"), reason="set VSM_LIVE=1 to hit the real backend")
def test_live_backend_smoke():
    be = make_backend("auto")
    r = LLMClient(be, use_cache=False).complete("Reply with the single word OK.", "Be terse.")
    assert "OK" in r.text.upper() and r.latency_s > 0


def test_binary_discovery_returns_executable_or_none():
    b = find_claude_binary()
    assert b is None or os.access(b, os.X_OK)


SKEL = '''
def wrap(xs: list) -> list:
    return [hole_transform(x) for x in xs if hole_keep(x)]

def hole_transform(x: int) -> int:
    """Return the transformed value."""
    raise NotImplementedError

def hole_keep(x: int) -> bool:
    ...

def helper():
    return 1

def check_invariants():
    xs = [1, 2]
    assert wrap([]) == []
    assert len(wrap(xs)) <= 2

check_invariants()
'''


def test_hole_utilities():
    from harness.codeutil import extract_invariants, find_holes, merge_fills, strip_toplevel_calls
    assert find_holes(SKEL) == ["hole_transform", "hole_keep"]
    inv = extract_invariants(SKEL)
    assert inv == ["xs = [1, 2]\nassert wrap([]) == []", "xs = [1, 2]\nassert len(wrap(xs)) <= 2"]
    stripped = strip_toplevel_calls(SKEL)
    assert "check_invariants()" not in stripped.replace("def check_invariants()", "")
    fills = "import math\ndef hole_transform(x):\n    return x * 2\ndef hole_keep(x):\n    return True\ndef wrap(xs):\n    return 'hijack'"
    prog, kept, n = merge_fills(stripped, fills, ["hole_transform", "hole_keep"])
    assert "hijack" not in kept and n == 5
    ns = {}
    exec(prog, ns)
    assert ns["wrap"]([1, 2]) == [2, 4]


def test_merge_fills_boundary():
    from harness.codeutil import merge_fills
    skel = "from __future__ import annotations\nLIMIT = 3\ndef api(x):\n    return hole_f(x)\ndef hole_f(x):\n    raise NotImplementedError\n"
    fills = ("from __future__ import annotations\nimport math\n_TABLE = {1: 10}\nLIMIT = 99\n"
             "def _helper(x):\n    return _TABLE.get(x, 0)\ndef hole_f(x):\n    return _helper(x) + LIMIT\n"
             "def api(x):\n    return 'hijack'\n")
    prog, kept, n = merge_fills(skel, fills, ["hole_f"])
    assert "hijack" not in kept and "LIMIT = 99" not in kept and "__future__" not in kept
    ns = {}
    exec(prog, ns)
    assert ns["api"](1) == 13
