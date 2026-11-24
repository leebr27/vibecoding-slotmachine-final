"""Browser demo: payloads are valid JSON built from results/, and the server is local-only and read-only."""
import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from demo import web_demo

HAS_RESULTS = (web_demo.RESULTS / "phase1" / "vibe" / "blind.jsonl").exists()
needs_results = pytest.mark.skipif(not HAS_RESULTS, reason="no recorded traces")


def test_clean_replaces_nan():
    out = web_demo._clean({"a": [1.0, float("nan")], "b": float("inf")})
    assert out == {"a": [1.0, None], "b": None}
    json.dumps(out, allow_nan=False)


@needs_results
def test_bootstrap_matches_summary():
    boot = web_demo.bootstrap("replay")
    json.dumps(boot, allow_nan=False)
    summary = json.loads((web_demo.RESULTS / "summary" / "phase1_vibe.json").read_text())
    assert boot["phase1"]["pass_rate"] == summary["pass_rate"]
    assert len(boot["tasks"]) == 30
    assert all(len(t["blind_outcomes"]) == 10 for t in boot["tasks"])
    assert boot["totals"]["calls"] > 0


@needs_results
def test_task_payload_shapes():
    d = web_demo.task_payload("orig_vending_machine")
    json.dumps(d, allow_nan=False)
    assert len(d["blind"]) == 10 and d["blind"][0]["tests"]
    assert d["error_paste"][0][0]["outcome"] != "pass"          # failing chains first
    p4 = d["sessions"]["typed_holes_patch"][0]
    assert "skeleton" in p4 and "fills" in p4
    p1 = d["sessions"]["retry_budget"][0]
    assert p1["extra"].get("handoff") or p1["decision_points"] > 0  # engaged sessions first
    with pytest.raises(KeyError):
        web_demo.task_payload("no_such_task")


@needs_results
def test_server_routes():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), web_demo.make_handler("replay", None))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def get(path, data=None):
        try:
            with urllib.request.urlopen(urllib.request.Request(base + path, data=data), timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    try:
        status, body = get("/")
        assert status == 200 and b"app.js" in body
        assert get("/app.js")[0] == 200
        assert json.loads(get("/api/bootstrap")[1])["mode"] == "replay"
        assert get("/api/task/he_fix_spaces")[0] == 200
        assert get("/api/task/nope")[0] == 404
        assert get("/%2e%2e/web_demo.py")[0] == 404
        assert get("/api/live/pull", data=b'{"task_id": "he_fix_spaces"}')[0] == 403
    finally:
        srv.shutdown()
        srv.server_close()


@needs_results
def test_task_payload_serves_realistic_sessions():
    d = web_demo.task_payload("he_fix_spaces")
    assert set(d["realistic"]) == set(web_demo.REALISTIC)
    if (web_demo.RESULTS / "phase3" / "slot_machine.jsonl").exists() and d["realistic"]["slot_machine"]:
        s = d["realistic"]["slot_machine"][0]
        assert "intent_pass" in s and "silent_failure" in s
        assert all("intent_outcome" in e for e in s["events"] if e["kind"] == "code")
