"""Phase 2: "nicotine patches", agency-preserving interventions.

Every intervention is a session protocol: given a task and a session index,
it drives the LLM, the sandbox and (where a human would act) a simulated
human, and records what the human SEES at each step. The baseline
`slot_machine` protocol is the Phase 1 error-paste loop.

Information parity: every condition observes the same terse request (vibe
prompt) and the same test-suite feedback; none sees the full specification.

Simulated human: where a protocol hands work to the programmer (filling
typed holes), a separately prompted model call stands in for a competent
human who sees only what the protocol shows them. Those calls are logged
with tag `human_proxy_*` and kept out of the agent's cost and latency; lines
they write count as human-authored. This is a stand-in, not a user study.

Event kinds (what the human is shown):
  code             a complete model-written program plus its test result (a "pull")
  best_of_n        Patch 2: the best of n hidden candidates plus a behavioural diff (a pull)
  hidden_attempt   Patch 3: an attempt whose code is withheld because it failed
  revealed         Patch 3: an attempt that passed every test, now shown
  diagnosis        Patch 3: a code-free failure diagnosis / conceptual hint
  scaffold         Patches 1 and 4: a skeleton with typed holes and invariants
  human_fill       the human's completed holes, run against the tests
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

from tasks import Task, TestCase
from .codeutil import code_lines, extract_code, extract_invariants, find_holes, merge_fills, strip_toplevel_calls
from .llm_client import LLMClient, LLMResponse
from .metrics import NEAR_MISS, PASS, classify
from .prompts import (DECOMPOSE, DIAGNOSIS, HOLE_FILL, HOLE_FILL_FEEDBACK, SKELETON, SYSTEM_CODER,
                      SYSTEM_DIAGNOSER, SYSTEM_HOLE_FILLER, SYSTEM_SCAFFOLDER, error_paste_prompt,
                      refined_prompt, task_prompt)
from .runner import Generation, generate_and_test, llm_meta
from .sandbox import ExecResult, run_tests

CONDITIONS = ("slot_machine", "retry_budget", "hidden_best_of_n", "test_gated_reveal", "typed_holes_patch")
PULL_KINDS = ("code", "best_of_n")


@dataclass
class Ctx:
    client: LLMClient
    style: str = "vibe"
    pool_size: int = 10      # number of Phase 1 blind samples per task (for best-of-n windows)
    human_rounds: int = 2    # fill rounds the simulated human gets after a handoff


@dataclass
class Session:
    condition: str
    task: Task
    idx: int
    events: list[dict] = field(default_factory=list)
    agent_calls: list[dict] = field(default_factory=list)
    proxy_calls: list[dict] = field(default_factory=list)
    agent_latency_s: float = 0.0
    proxy_latency_s: float = 0.0
    final_pass: bool = False
    model_only_pass: bool = False
    decision_points: int = 0
    review_items: int = 0
    passive_retries: int = 0
    human_lines: int = 0
    total_lines: int = 0
    final_code: str = ""
    invariants: list[str] = field(default_factory=list)
    invariants_valid_ref: int = 0
    invariants_hold_final: int = 0
    hole_compliant: bool | None = None
    extra: dict = field(default_factory=dict)

    # --- bookkeeping -----------------------------------------------------
    def agent(self, resp: LLMResponse, sandbox_s: float = 0.0, parallel: bool = False) -> None:
        self.agent_calls.append(llm_meta(resp))
        if not parallel:
            self.agent_latency_s += resp.latency_s + sandbox_s

    def proxy(self, resp: LLMResponse) -> None:
        self.proxy_calls.append(llm_meta(resp))
        self.proxy_latency_s += resp.latency_s

    def event(self, kind: str, outcome: str | None = None, result: ExecResult | None = None, **kw) -> None:
        e = {"kind": kind, "outcome": outcome}
        if result is not None:
            e.update(n_pass=result.n_pass, n_total=result.n_total, frac=round(result.frac, 4),
                     failed_tests=[o.name for o in result.failed()])
        e.update(kw)
        self.events.append(e)

    def to_dict(self) -> dict:
        pulls = [e for e in self.events if e["kind"] in PULL_KINDS]
        a_in = sum(c["input_tokens"] for c in self.agent_calls)
        a_out = sum(c["output_tokens"] for c in self.agent_calls)
        return {
            "condition": self.condition, "task_id": self.task.task_id, "suite": self.task.suite,
            "session": self.idx, "final_pass": self.final_pass, "model_only_pass": self.model_only_pass,
            "n_pulls": len(pulls), "pull_outcomes": [e["outcome"] for e in pulls],
            "visible_near_misses": sum(e["outcome"] == NEAR_MISS for e in pulls),
            "passive_retries": self.passive_retries, "decision_points": self.decision_points,
            "review_items": self.review_items, "human_lines": self.human_lines,
            "total_lines": self.total_lines,
            "human_line_frac": self.human_lines / self.total_lines if self.total_lines else 0.0,
            "invariants_total": len(self.invariants), "invariants_valid_ref": self.invariants_valid_ref,
            "invariants_hold_final": self.invariants_hold_final, "hole_compliant": self.hole_compliant,
            "agent_calls": len(self.agent_calls), "agent_input_tokens": a_in, "agent_output_tokens": a_out,
            "agent_cost_usd": sum(c["cost_usd"] for c in self.agent_calls),
            "agent_latency_s": round(self.agent_latency_s, 3),
            "proxy_calls": len(self.proxy_calls),
            "proxy_tokens": sum(c["input_tokens"] + c["output_tokens"] for c in self.proxy_calls),
            "proxy_latency_s": round(self.proxy_latency_s, 3),
            "events": self.events, "final_code": self.final_code, "invariants": self.invariants,
            "call_keys": [c["key"] for c in self.agent_calls + self.proxy_calls], "extra": self.extra,
        }


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _gen(ctx: Ctx, s: Session, prompt: str, sample: int, tag: str, parallel: bool = False) -> Generation:
    g = generate_and_test(ctx.client, s.task, prompt, sample=sample, tag=tag)
    s.agent(g.resp, g.result.wall_s, parallel=parallel)
    return g


def _code_event(s: Session, g: Generation, kind: str = "code", **kw) -> None:
    s.event(kind, g.outcome, g.result, **kw)


def check_invariants_against(code: str, task: Task, invariants: list[str]) -> int:
    """How many model-written invariants hold when run against `code`."""
    if not invariants:
        return 0
    probe = replace(task, tests=tuple(TestCase(f"inv{i}", src) for i, src in enumerate(invariants)),
                    test_prelude="")
    return run_tests(code, probe).n_pass


# Fenced code, inline code containing operators/calls, function definitions,
# lambdas, or indented code lines. Plain identifiers in backticks are allowed.
_CODE_MARKERS = re.compile(r"```|`[^`]*[()=\[\]{}][^`]*`|\bdef\s+\w+\s*\(|\blambda\b|^\s{4}\S", re.M)


def is_code_free(text: str) -> bool:
    return not _CODE_MARKERS.search(text or "")


def behavioural_diff(cands: list[Generation], best: int, task: Task) -> dict:
    """Deterministic differential-testing summary of hidden candidates."""
    vecs = [c.result.pass_vector() for c in cands]
    names = [tc.name for tc in task.tests]
    disagree = []
    for i, name in enumerate(names):
        col = [v[i] if i < len(v) else False for v in vecs]
        if len(set(col)) > 1:
            disagree.append({"test": name, "n_pass": sum(col), "surfaced_passes": col[best]})
    resolved = [d["test"] for d in disagree if d["surfaced_passes"]]
    unresolved = [o.name for o in cands[best].result.failed()]
    lines = [f"Surfaced candidate {best + 1} of {len(cands)}: passes "
             f"{cands[best].result.n_pass}/{cands[best].result.n_total} tests.",
             f"Hidden candidates showed {len(set(vecs))} distinct behaviours."]
    if disagree:
        lines.append("They disagreed on: " + ", ".join(
            f"{d['test']} ({d['n_pass']}/{len(cands)} passed; surfaced {'passes' if d['surfaced_passes'] else 'fails'})"
            for d in disagree))
    if resolved:
        lines.append("Edge cases resolved by the surfaced choice: " + ", ".join(resolved))
    if unresolved:
        lines.append("Still failing: " + ", ".join(unresolved))
    return {"disagree": disagree, "distinct": len(set(vecs)), "resolved": resolved,
            "unresolved": unresolved, "text": "\n".join(lines)}


def _human_fill(ctx: Ctx, s: Session, skeleton: str, holes: list[str], rounds: int, sample: int,
                tag: str) -> tuple[str, ExecResult | None, int]:
    """Simulated programmer fills the holes, re-running the tests between rounds."""
    fills_src, report, program, res, n_lines = "", "", skeleton, None, 0
    request = task_prompt(s.task, ctx.style)
    for r in range(1, rounds + 1):
        feedback = HOLE_FILL_FEEDBACK.format(fills=fills_src, report=report) if r > 1 else ""
        resp = ctx.client.complete(HOLE_FILL.format(request=request, skeleton=skeleton, feedback=feedback),
                                   SYSTEM_HOLE_FILLER, sample=sample, tag=f"human_proxy_{tag}")
        s.proxy(resp)
        program, kept, n_lines = merge_fills(skeleton, extract_code(resp.text), holes)
        res = run_tests(program, s.task)
        out = classify(res.n_pass, res.n_total, res.syntax_ok)
        s.event("human_fill", out, res, round=r, fill_lines=n_lines)
        if out == PASS:
            break
        fills_src, report = kept, res.failure_report(s.task)
    return program, res, n_lines


def _scaffold(ctx: Ctx, s: Session, prompt: str, sample: int, tag: str) -> tuple[str, list[str]]:
    resp = ctx.client.complete(prompt, SYSTEM_SCAFFOLDER, sample=sample, tag=tag)
    s.agent(resp)
    skeleton = strip_toplevel_calls(extract_code(resp.text))
    holes = find_holes(skeleton)
    s.invariants = extract_invariants(skeleton)
    s.invariants_valid_ref = check_invariants_against(s.task.reference, s.task, s.invariants)
    s.hole_compliant = bool(holes)
    s.event("scaffold", None, holes=holes, n_invariants=len(s.invariants),
            invariants_valid_ref=s.invariants_valid_ref, skeleton_lines=code_lines(skeleton))
    return skeleton, holes


def _finish_with_holes(ctx: Ctx, s: Session, skeleton: str, holes: list[str], sample: int, tag: str) -> None:
    if not holes:
        # Non-compliant scaffold: the model wrote a complete program anyway. Show it as a pull.
        res = run_tests(skeleton, s.task)
        out = classify(res.n_pass, res.n_total, res.syntax_ok)
        s.event("code", out, res, note="scaffold had no holes")
        s.final_pass = s.model_only_pass = out == PASS
        s.final_code, s.total_lines = skeleton, code_lines(skeleton)
        return
    s.decision_points += len(holes)
    program, res, n_lines = _human_fill(ctx, s, skeleton, holes, ctx.human_rounds, sample, tag)
    s.final_code = program
    s.final_pass = bool(res and res.all_pass)
    s.human_lines, s.total_lines = n_lines, code_lines(program)
    s.invariants_hold_final = check_invariants_against(program, s.task, s.invariants)


# ---------------------------------------------------------------------------
# Baseline and the four patches
# ---------------------------------------------------------------------------
def slot_machine(ctx: Ctx, task: Task, j: int, max_turns: int = 5) -> Session:
    """Unpatched vibecoding: every attempt is shown; paste the error, retry."""
    s = Session("slot_machine", task, j)
    history = []
    for t in range(1, max_turns + 1):
        prompt = task_prompt(task, ctx.style) if t == 1 else error_paste_prompt(task, history, ctx.style)
        g = _gen(ctx, s, prompt, j, f"blind:{ctx.style}" if t == 1 else f"error_paste:{ctx.style}")
        _code_event(s, g, turn=t)
        s.final_code = g.code
        if g.outcome == PASS:
            s.final_pass = s.model_only_pass = True
            break
        history.append((g.code, g.result.failure_report(task)))
    s.passive_retries = len(s.events) - 1
    s.total_lines = code_lines(s.final_code)
    return s


def retry_budget(ctx: Ctx, task: Task, j: int, k: int = 2) -> Session:
    """Patch 1: at most k automatic attempts, then a mandatory decomposition
    handoff: a skeleton whose holes contain the decisions the failures implicate."""
    s = Session("retry_budget", task, j)
    history, last = [], None
    for t in range(1, k + 1):
        prompt = task_prompt(task, ctx.style) if t == 1 else error_paste_prompt(task, history, ctx.style)
        last = _gen(ctx, s, prompt, j, f"blind:{ctx.style}" if t == 1 else f"error_paste:{ctx.style}")
        _code_event(s, last, turn=t)
        s.final_code = last.code
        if last.outcome == PASS:
            s.final_pass = s.model_only_pass = True
            s.passive_retries = t - 1
            s.total_lines = code_lines(last.code)
            return s
        history.append((last.code, last.result.failure_report(task)))
    s.passive_retries = k - 1
    s.extra["handoff"] = True
    prompt = DECOMPOSE.format(request=task_prompt(task, ctx.style), code=last.code.rstrip(),
                              report=last.result.failure_report(task))
    skeleton, holes = _scaffold(ctx, s, prompt, j, "p1_decompose")
    _finish_with_holes(ctx, s, skeleton, holes, j, "p1_fill")
    return s


def hidden_best_of_n(ctx: Ctx, task: Task, j: int, n: int = 5, rounds: int = 2) -> Session:
    """Patch 2: sample n candidates privately, test them, surface only the best
    one together with a behavioural diff of what the hidden candidates disagreed on."""
    s = Session("hidden_best_of_n", task, j)
    history = []
    for r in range(1, rounds + 1):
        if r == 1:  # reuse Phase 1 blind pulls: window j..j+n-1 of the sample pool
            prompt, samples = task_prompt(task, ctx.style), [(j + i) % ctx.pool_size for i in range(n)]
            tag = f"blind:{ctx.style}"
        else:
            prompt, samples, tag = error_paste_prompt(task, history, ctx.style), list(range(n)), "p2_round"
        cands = [_gen(ctx, s, prompt, smp, tag, parallel=True) for smp in samples]
        s.agent_latency_s += max(c.resp.latency_s + c.result.wall_s for c in cands)  # sampled in parallel
        best = max(range(n), key=lambda i: (cands[i].result.n_pass, -i))
        diff = behavioural_diff(cands, best, task)
        s.review_items += len(diff["disagree"])
        _code_event(s, cands[best], "best_of_n", round=r, diff=diff["text"], distinct=diff["distinct"],
                    hidden_outcomes=[c.outcome for c in cands])
        s.final_code = cands[best].code
        if cands[best].outcome == PASS:
            s.final_pass = s.model_only_pass = True
            break
        history.append((cands[best].code, cands[best].result.failure_report(task)))
    s.passive_retries = sum(e["kind"] == "best_of_n" for e in s.events) - 1
    s.total_lines = code_lines(s.final_code)
    return s


def test_gated_reveal(ctx: Ctx, task: Task, j: int, k: int = 2) -> Session:
    """Patch 3: code is shown only if it passes every test. A failed attempt yields
    a code-free diagnosis that the programmer adds to their spec as a clarification."""
    s = Session("test_gated_reveal", task, j)
    clar: list[str] = []
    hints_code_free = []
    for t in range(1, k + 1):
        prompt = refined_prompt(task, clar, ctx.style)
        g = _gen(ctx, s, prompt, j, f"blind:{ctx.style}" if t == 1 else "p3_regen")
        if g.outcome == PASS:
            _code_event(s, g, "revealed", turn=t)
            s.final_pass = s.model_only_pass = True
            s.final_code = g.code
            s.total_lines = code_lines(g.code)
            break
        s.event("hidden_attempt", "hidden", None, turn=t, true_outcome=g.outcome,
                n_pass=g.result.n_pass, n_total=g.result.n_total)
        resp = ctx.client.complete(DIAGNOSIS.format(request=prompt, report=g.result.failure_report(task),
                                                    code=g.code.rstrip()), SYSTEM_DIAGNOSER, sample=j,
                                   tag="p3_diagnosis")
        s.agent(resp)
        hint = " ".join(resp.text.strip().split())
        hints_code_free.append(is_code_free(hint))
        s.event("diagnosis", None, text=hint, code_free=hints_code_free[-1], turn=t)
        s.review_items += 1
        if t < k:
            clar.append(hint)
            s.decision_points += 1  # the programmer must accept/edit the clarification
    s.extra["clarifications"] = clar
    s.extra["hints_code_free"] = hints_code_free
    return s


test_gated_reveal.__test__ = False  # not a pytest test despite the name


def typed_holes_patch(ctx: Ctx, task: Task, j: int, rounds: int = 2) -> Session:
    """Patch 4: spec-first, hole-driven co-programming. The agent writes the API,
    boilerplate and executable invariants; core decisions are typed holes the
    programmer fills. Retries iterate on the programmer's holes, never re-roll the program."""
    s = Session("typed_holes_patch", task, j)
    skeleton, holes = _scaffold(ctx, s, SKELETON.format(request=task_prompt(task, ctx.style)), j, "p4_skeleton")
    _finish_with_holes(replace(ctx, human_rounds=rounds), s, skeleton, holes, j, "p4_fill")
    return s


def run_condition(ctx: Ctx, condition: str, task: Task, j: int, k: int) -> Session:
    if condition == "slot_machine":
        return slot_machine(ctx, task, j, max_turns=5)
    if condition == "retry_budget":
        return retry_budget(ctx, task, j, k=k)
    if condition == "hidden_best_of_n":
        return hidden_best_of_n(ctx, task, j, n=5, rounds=k)
    if condition == "test_gated_reveal":
        return test_gated_reveal(ctx, task, j, k=k)
    if condition == "typed_holes_patch":
        return typed_holes_patch(ctx, task, j, rounds=k)
    raise ValueError(condition)
