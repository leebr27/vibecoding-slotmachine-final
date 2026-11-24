"""Sandboxed execution of candidate programs against a task's test suite.

Each evaluation runs in a fresh `python -I` subprocess in an empty temporary
directory with a scrubbed environment, closed stdin and a CPU rlimit. Inside
the child, every test case runs separately under its own interval-timer
timeout, so one infinite loop costs one test, not the whole suite. A
suite-level wall-clock timeout kills the child if it hangs anyway; results
are streamed line by line, so tests that finished before the kill still count.

This is process isolation, not a security boundary: run untrusted model
output only on a machine you are comfortable running it on.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from tasks.schema import Task

PER_TEST_TIMEOUT_S = 2.0
SUITE_TIMEOUT_S = 10.0

# The child-side runner. Kept as a string so the sandbox has no import-time
# dependency on the parent package inside the child process.
_RUNNER = r'''
import ast, io, json, signal, sys, time, contextlib

class _TestTimeout(BaseException):
    pass

def _on_alarm(signum, frame):
    raise _TestTimeout()

def _short(x, n=240):
    try:
        r = repr(x)
    except Exception as e:  # noqa
        r = f"<unreprable {type(e).__name__}>"
    return r if len(r) <= n else r[: n - 3] + "..."

def __vsm_assert_eq(left, right, src):
    if not (left == right):
        raise AssertionError(f"{src}\n  got:      {_short(left)}\n  expected: {_short(right)}")

class _Rewrite(ast.NodeTransformer):
    """pytest-style assertion rewriting for `assert a == b` statements."""
    def __init__(self, source):
        self.source = source
    def visit_Assert(self, node):
        t = node.test
        src = ast.get_source_segment(self.source, node) or "assert ..."
        if isinstance(t, ast.Compare) and len(t.ops) == 1 and isinstance(t.ops[0], ast.Eq):
            call = ast.Call(func=ast.Name("__vsm_assert_eq", ast.Load()),
                            args=[t.left, t.comparators[0], ast.Constant(src)], keywords=[])
            return ast.copy_location(ast.Expr(call), node)
        if node.msg is None:
            node.msg = ast.Constant(src)
        return node

def main():
    payload = json.load(open(sys.argv[1]))
    out = open(sys.argv[2], "w", buffering=1)
    per_test = payload["per_test_timeout"]
    signal.signal(signal.SIGALRM, _on_alarm)
    sink = io.StringIO()
    ns = {"__name__": "candidate", "__source__": payload["code"],
          "__vsm_assert_eq": __vsm_assert_eq}
    load_error = None
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            signal.setitimer(signal.ITIMER_REAL, per_test * 2)
            try:
                exec(compile(payload["code"], "candidate.py", "exec"), ns)
                if payload.get("prelude"):
                    exec(compile(payload["prelude"], "prelude.py", "exec"), ns)
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
    except _TestTimeout:
        load_error = ("Timeout", "module load timed out")
    except BaseException as e:  # SyntaxError, ImportError, SystemExit, ...
        load_error = (type(e).__name__, str(e)[:500])
    out.write(json.dumps({"kind": "load", "error": load_error}) + "\n")
    for t in payload["tests"]:
        rec = {"kind": "test", "name": t["name"], "passed": False,
               "error_type": None, "message": ""}
        start = time.perf_counter()
        if load_error is not None:
            rec["error_type"], rec["message"] = load_error
        else:
            try:
                tree = _Rewrite(t["code"]).visit(ast.parse(t["code"]))
                ast.fix_missing_locations(tree)
                code = compile(tree, f"test_{t['name']}", "exec")
                with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                    signal.setitimer(signal.ITIMER_REAL, per_test)
                    try:
                        exec(code, dict(ns))
                    finally:
                        signal.setitimer(signal.ITIMER_REAL, 0)
                rec["passed"] = True
            except _TestTimeout:
                rec["error_type"], rec["message"] = "Timeout", f"test exceeded {per_test}s"
            except BaseException as e:
                rec["error_type"], rec["message"] = type(e).__name__, str(e)[:800]
        rec["duration_s"] = round(time.perf_counter() - start, 5)
        out.write(json.dumps(rec) + "\n")
    out.write(json.dumps({"kind": "stdout", "text": sink.getvalue()[:4000]}) + "\n")

main()
'''


@dataclass
class TestOutcome:
    name: str
    passed: bool
    error_type: str | None = None
    message: str = ""
    duration_s: float = 0.0


@dataclass
class ExecResult:
    task_id: str
    n_pass: int
    n_total: int
    outcomes: list[TestOutcome] = field(default_factory=list)
    load_error: tuple[str, str] | None = None
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""
    wall_s: float = 0.0

    @property
    def frac(self) -> float:
        return self.n_pass / self.n_total if self.n_total else 0.0

    @property
    def all_pass(self) -> bool:
        return self.n_total > 0 and self.n_pass == self.n_total

    @property
    def syntax_ok(self) -> bool:
        return not (self.load_error and self.load_error[0] in ("SyntaxError", "IndentationError", "TabError"))

    def pass_vector(self) -> tuple[bool, ...]:
        return tuple(o.passed for o in self.outcomes)

    def failed(self) -> list[TestOutcome]:
        return [o for o in self.outcomes if not o.passed]

    def to_dict(self) -> dict:
        d = asdict(self)
        d["frac"] = self.frac
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ExecResult":
        d = dict(d)
        d.pop("frac", None)
        d["outcomes"] = [TestOutcome(**o) for o in d.get("outcomes", [])]
        if d.get("load_error"):
            d["load_error"] = tuple(d["load_error"])
        return cls(**d)

    def failure_report(self, task: Task | None = None, max_failures: int = 6) -> str:
        """Render failures the way a developer would paste pytest output."""
        if self.load_error:
            et, msg = self.load_error
            return f"ERROR collecting candidate.py\n{et}: {msg}\n{self.n_total} errors"
        lines = []
        srcs = {tc.name: tc.code for tc in task.tests} if task else {}
        for o in self.failed()[:max_failures]:
            lines.append(f"FAILED test_{o.name} - {o.error_type}")
            msg = o.message.strip()
            if not msg and o.name in srcs:
                msg = srcs[o.name]
            if msg:
                lines.extend("    " + ln for ln in msg.splitlines()[:8])
        extra = len(self.failed()) - max_failures
        if extra > 0:
            lines.append(f"... and {extra} more failures")
        lines.append(f"{self.n_total - self.n_pass} failed, {self.n_pass} passed")
        return "\n".join(lines)


def _limit_resources():  # pragma: no cover - runs in the child
    try:
        import resource
        cpu = int(SUITE_TIMEOUT_S) + 2
        resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    except Exception:
        pass


def run_tests(code: str, task: Task, per_test_timeout: float = PER_TEST_TIMEOUT_S,
              suite_timeout: float = SUITE_TIMEOUT_S) -> ExecResult:
    """Execute `code` against `task.tests` in an isolated subprocess."""
    start = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="vsm_") as tmp:
        tmpd = Path(tmp)
        (tmpd / "runner.py").write_text(_RUNNER)
        payload = {
            "code": code,
            "prelude": task.test_prelude,
            "tests": [{"name": tc.name, "code": tc.code} for tc in task.tests],
            "per_test_timeout": per_test_timeout,
        }
        (tmpd / "payload.json").write_text(json.dumps(payload))
        out_path = tmpd / "results.jsonl"
        env = {"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"}
        timed_out = False
        stderr = ""
        try:
            proc = subprocess.run(
                [sys.executable, "-I", str(tmpd / "runner.py"), str(tmpd / "payload.json"), str(out_path)],
                cwd=tmp, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                timeout=suite_timeout, preexec_fn=_limit_resources if os.name == "posix" else None,
            )
            stderr = proc.stderr[-4000:]
        except subprocess.TimeoutExpired as e:
            timed_out = True
            stderr = (e.stderr or b"")[-4000:].decode("utf-8", "replace") if isinstance(e.stderr, bytes) else (e.stderr or "")
        records = []
        if out_path.exists():
            for line in out_path.read_text().splitlines():
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass  # partially written final line after a kill
    load_error = None
    stdout = ""
    by_name: dict[str, TestOutcome] = {}
    for r in records:
        if r["kind"] == "load" and r["error"]:
            load_error = tuple(r["error"])
        elif r["kind"] == "test":
            by_name[r["name"]] = TestOutcome(r["name"], r["passed"], r["error_type"], r["message"], r.get("duration_s", 0.0))
        elif r["kind"] == "stdout":
            stdout = r["text"]
    outcomes = []
    for tc in task.tests:
        if tc.name in by_name:
            outcomes.append(by_name[tc.name])
        else:  # never reached: suite timeout or crash of the child
            outcomes.append(TestOutcome(tc.name, False, "Timeout" if timed_out else "Crash",
                                        "suite killed before this test ran"))
    return ExecResult(
        task_id=task.task_id,
        n_pass=sum(o.passed for o in outcomes),
        n_total=len(outcomes),
        outcomes=outcomes,
        load_error=load_error,
        timed_out=timed_out,
        stdout=stdout,
        stderr=stderr,
        wall_s=round(time.perf_counter() - start, 4),
    )
