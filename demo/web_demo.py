#!/usr/bin/env python3
"""Is Vibecoding a Slot Machine? -- browser demo served on localhost.

    python demo/web_demo.py                 # replay recorded traces (offline), opens the browser
    python demo/web_demo.py --live          # also allow real generations through the configured backend
    python demo/web_demo.py --port 9000 --no-browser

Standard library only. The page is a static bundle in demo/web/; every number and every line of
code it shows comes from results/ (replay) or from a fresh model call (live). Phase 2 sessions
(complete test feedback) and Phase 3 sessions (realistic feedback: the programmer's own few tests,
held-out tests for scoring) can both be replayed.
"""
from __future__ import annotations

import argparse
import json
import math
import mimetypes
import sys
import threading
import time
import webbrowser
from functools import lru_cache
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from harness.store import JsonlStore  # noqa: E402
from tasks import get_task, load_tasks  # noqa: E402

RESULTS = ROOT / "results"
STATIC = Path(__file__).resolve().parent / "web"
CONDITIONS = ["slot_machine", "retry_budget", "hidden_best_of_n", "test_gated_reveal", "typed_holes_patch"]
REALISTIC = ["slot_machine", "attentive", "retry_budget", "hidden_best_of_n", "test_gated_reveal",
             "typed_holes_patch", "typed_holes_fixed"]
SUGGESTED = ["he_fix_spaces", "orig_vending_machine", "orig_wrap_text", "orig_parser_combinators",
             "mbpp_parse_kv", "he_make_palindrome"]
HOLE_MARKER = "# ---- holes filled by the programmer ----"


# ---------------------------------------------------------------------------- JSON helpers
def _clean(x):
    """Replace NaN/inf with None so the payload is valid JSON for browsers."""
    if isinstance(x, float):
        return None if (math.isnan(x) or math.isinf(x)) else x
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


def _read_json(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


# ---------------------------------------------------------------------------- record shaping
def slim_attempt(r: dict) -> dict:
    """The fields of an attempt record the page renders (code, outcome, per-test results)."""
    outcomes = (r.get("exec") or {}).get("outcomes") or []
    return {
        "chain": r.get("chain"), "turn": r.get("turn"), "outcome": r["outcome"],
        "n_pass": r["n_pass"], "n_total": r["n_total"], "failed_tests": r.get("failed_tests", []),
        "load_error": r.get("load_error"), "code": r.get("code", ""),
        "tests": [{"name": o["name"], "passed": o["passed"], "message": o.get("message") or ""}
                  for o in outcomes],
    }


SESSION_KEYS = ("condition", "variant", "k", "session", "final_pass", "model_only_pass", "n_pulls",
                "pull_outcomes", "visible_near_misses", "passive_retries", "decision_points",
                "review_items", "human_lines", "total_lines", "invariants_total", "invariants_valid_ref",
                "invariants_hold_final", "agent_calls", "agent_input_tokens", "agent_output_tokens",
                "agent_cost_usd", "agent_latency_s", "proxy_calls", "events", "final_code", "invariants",
                "extra", "intent_pass", "visible_pass", "silent_failure", "human_turns", "shown_lines",
                "n_visible")


def slim_session(s: dict) -> dict:
    out = {k: s.get(k) for k in SESSION_KEYS}
    out.setdefault("variant", s.get("condition"))
    code = s.get("final_code") or ""
    if HOLE_MARKER in code:
        out["skeleton"], out["fills"] = (part.strip("\n") for part in code.split(HOLE_MARKER, 1))
    return out


def _engaged_first(sessions: list[dict]) -> list[dict]:
    """Sessions where the intervention actually did something come first (e.g. a P1 handoff, or
    under realistic feedback a silent failure the programmer could not see)."""
    def key(s):
        engaged = (bool((s.get("extra") or {}).get("handoff")) or (s.get("decision_points") or 0) > 0
                   or bool(s.get("silent_failure")))
        return (not engaged, -len(s.get("events") or []), s.get("variant") or "", s.get("session") or 0)
    return sorted(sessions, key=key)


# ---------------------------------------------------------------------------- cached data
@lru_cache(maxsize=1)
def _phase1_records():
    blind, ep = {}, {}
    for r in JsonlStore(RESULTS / "phase1" / "vibe" / "blind.jsonl").load():
        blind.setdefault(r["task_id"], []).append(r)
    for r in JsonlStore(RESULTS / "phase1" / "vibe" / "error_paste.jsonl").load():
        ep.setdefault(r["task_id"], {}).setdefault(r["chain"], []).append(r)
    return blind, ep


@lru_cache(maxsize=1)
def _phase2_records():
    out: dict[tuple[str, str], list[dict]] = {}
    for path in sorted((RESULTS / "phase2").glob("*.jsonl")):
        for r in JsonlStore(path).load():
            out.setdefault((r["condition"], r["task_id"]), []).append(r)
    return out


@lru_cache(maxsize=1)
def _phase3_records():
    out: dict[tuple[str, str], list[dict]] = {}
    for name in REALISTIC:
        for r in JsonlStore(RESULTS / "phase3" / f"{name}.jsonl").load():
            out.setdefault((name, r["task_id"]), []).append(r)
    return out


@lru_cache(maxsize=1)
def _call_totals() -> dict:
    n, cost, models = 0, 0.0, set()
    path = RESULTS / "raw" / "llm_calls.jsonl"
    if path.exists():
        with path.open() as f:
            for line in f:
                r = json.loads(line)
                n += 1
                cost += r.get("cost_usd") or 0.0
                if r.get("model"):
                    models.add(r["model"])
    return {"calls": n, "cost_usd": round(cost, 2), "models": sorted(models)}


def bootstrap(mode: str) -> dict:
    """Everything the page needs at load: task index, Phase 1 headline numbers, Phase 2 table."""
    p1 = _read_json(RESULTS / "summary" / "phase1_vibe.json") or {}
    p1s = _read_json(RESULTS / "summary" / "phase1_spec.json") or {}
    p2 = _read_json(RESULTS / "summary" / "phase2.json") or {}
    p3 = _read_json(RESULTS / "summary" / "phase3.json") or {}
    blind, _ = _phase1_records()
    per_task = p1.get("per_task", {})
    tasks = []
    for t in load_tasks():
        recs = sorted(blind.get(t.task_id, []), key=lambda r: r["chain"])
        st = per_task.get(t.task_id, {})
        tasks.append({
            "task_id": t.task_id, "suite": t.suite, "title": t.title, "vibe_prompt": t.vibe_prompt,
            "spec_prompt": t.prompt, "entry_points": list(t.entry_points),
            "tests": [tc.name for tc in t.tests], "suggested": t.task_id in SUGGESTED,
            "blind_outcomes": [r["outcome"] for r in recs],
            "p_pass": st.get("p_pass"), "entropy": st.get("entropy_pass"),
        })
    phase1_keys = ("n_tasks", "n_blind_attempts", "outcome_counts", "pass_rate", "pass_rate_ci",
                   "p_nm_given_failure", "median_frac_tests_passed_in_failures", "mean_entropy_bits",
                   "n_tasks_always_pass", "n_tasks_never_pass", "n_tasks_stochastic",
                   "mean_distinct_behaviours_per_task", "mean_pairwise_code_similarity_blind",
                   "blind_curve", "error_paste_curve", "error_paste_transitions", "k_star")
    return _clean({
        "mode": mode, "totals": _call_totals(), "tasks": tasks,
        "phase1": {k: p1.get(k) for k in phase1_keys},
        "spec": {"pass_rate": p1s.get("pass_rate"), "n": p1s.get("n_blind_attempts"),
                 "mean_entropy_bits": p1s.get("mean_entropy_bits")},
        "phase2": {"order": p2.get("order", []), "labels": p2.get("labels", {}),
                   "variants": p2.get("variants", {})},
        "phase3": {"order": p3.get("order", []), "labels": p3.get("labels", {}),
                   "variants": p3.get("variants", {}), "n_visible": (p3.get("meta") or {}).get("n_visible", 3)},
    })


def task_payload(task_id: str) -> dict:
    get_task(task_id)  # raises KeyError for unknown ids
    blind, ep = _phase1_records()
    p2 = _phase2_records()
    chains = ep.get(task_id, {})
    # Chains that start with a failure first: that is where the error-paste loop is visible.
    order = sorted(chains, key=lambda c: (chains[c][0]["outcome"] == "pass", c))
    sessions = {}
    for cond in CONDITIONS:
        recs = [slim_session(s) for s in p2.get((cond, task_id), [])]
        sessions[cond] = _engaged_first(recs)
    p3 = _phase3_records()
    realistic = {name: _engaged_first([slim_session(s) for s in p3.get((name, task_id), [])])
                 for name in REALISTIC}
    return _clean({
        "task_id": task_id,
        "blind": [slim_attempt(r) for r in sorted(blind.get(task_id, []), key=lambda r: r["chain"])],
        "error_paste": [[slim_attempt(r) for r in sorted(chains[c], key=lambda r: r["turn"])] for c in order],
        "sessions": sessions,
        "realistic": realistic,
    })


# ---------------------------------------------------------------------------- live mode
class Live:
    """Real generations through the configured backend (only when --live is passed)."""

    def __init__(self, backend: str, model: str):
        self.backend, self.model = backend, model
        self._client = None
        self._lock = threading.Lock()
        self._n = 0

    def client(self):
        with self._lock:
            if self._client is None:
                from harness.llm_client import LLMClient, make_backend
                self._client = LLMClient(make_backend(self.backend, self.model),
                                         RESULTS / "raw" / "demo_calls.jsonl")
            return self._client

    def fresh(self) -> int:
        with self._lock:
            self._n += 1
            return 100_000 + int(time.time()) % 100_000 * 10 + self._n

    def pull(self, task_id: str) -> dict:
        from harness.prompts import task_prompt
        from harness.runner import attempt_record, generate_and_test
        task = get_task(task_id)
        g = generate_and_test(self.client(), task, task_prompt(task), self.fresh(), "demo_pull")
        return slim_attempt(attempt_record(task, "blind", 0, 1, g))

    def error_paste(self, task_id: str) -> list[dict]:
        from harness.runner import run_error_paste_unit
        return [slim_attempt(r) for r in run_error_paste_unit(self.client(), get_task(task_id), self.fresh(), 5)]

    def patch(self, task_id: str, cond: str) -> dict:
        from harness.patches import Ctx, run_condition
        meta = _read_json(RESULTS / "phase2" / "meta.json") or {}
        s = run_condition(Ctx(self.client(), pool_size=10 ** 9), cond, get_task(task_id), self.fresh(),
                          meta.get("k_star", 3))
        return slim_session(s.to_dict())


# ---------------------------------------------------------------------------- HTTP
def make_handler(mode: str, live: Live | None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "VSMDemo/1.0"

        def log_message(self, fmt, *args):  # quiet by default
            pass

        def _send(self, status: int, body: bytes, ctype: str):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, status: int = 200):
            self._send(status, json.dumps(obj, allow_nan=False).encode(), "application/json")

        def _error(self, status: int, msg: str):
            self._json({"error": msg}, status)

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            try:
                if path == "/api/bootstrap":
                    return self._json(bootstrap(mode))
                if path.startswith("/api/task/"):
                    return self._json(task_payload(path.rsplit("/", 1)[-1]))
            except KeyError as e:
                return self._error(HTTPStatus.NOT_FOUND, f"unknown task {e}")
            if path in ("", "/"):
                path = "/index.html"
            target = (STATIC / path.lstrip("/")).resolve()
            if STATIC.resolve() not in target.parents or not target.is_file():
                return self._error(HTTPStatus.NOT_FOUND, "not found")
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, target.read_bytes(), ctype)

        def do_POST(self):
            path = urlparse(self.path).path
            if live is None:
                return self._error(HTTPStatus.FORBIDDEN, "live mode is off; restart with --live")
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                task_id = body["task_id"]
                if path == "/api/live/pull":
                    return self._json(_clean(live.pull(task_id)))
                if path == "/api/live/error_paste":
                    return self._json(_clean(live.error_paste(task_id)))
                if path == "/api/live/patch":
                    cond = body["condition"]
                    if cond not in CONDITIONS:
                        return self._error(HTTPStatus.BAD_REQUEST, "unknown condition")
                    return self._json(_clean(live.patch(task_id, cond)))
                return self._error(HTTPStatus.NOT_FOUND, "not found")
            except KeyError as e:
                return self._error(HTTPStatus.BAD_REQUEST, f"missing or unknown {e}")
            except Exception as e:  # surface backend failures to the page instead of hanging
                return self._error(HTTPStatus.BAD_GATEWAY, f"{type(e).__name__}: {e}")

    return Handler


def serve(port: int, mode: str, live: Live | None, open_browser: bool) -> None:
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(mode, live))
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    print(f"Vibecoding slot machine demo ({mode}) at {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        srv.server_close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--live", action="store_true", help="enable real generations (needs a backend)")
    ap.add_argument("--backend", default="auto")
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args(argv)
    if not (RESULTS / "phase1" / "vibe" / "blind.jsonl").exists():
        sys.exit("No recorded traces in results/. Run the experiments first.")
    live = Live(args.backend, args.model) if args.live else None
    serve(args.port, "live" if live else "replay", live, not args.no_browser)


if __name__ == "__main__":
    main()
