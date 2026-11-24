"""Phase 3: the patches under realistic feedback.

Phase 2 gives every condition feedback from the complete hidden test suite, whose
failure messages include the expected values. That is the best case for pasting
errors, and no patch has information the baseline lacks. Phase 3 changes two things:

1. Visible vs held-out tests. The programmer owns only the first N_VISIBLE tests of
   each task (a rule fixed before any run; tests were ordered when the benchmark was
   written). All feedback anyone sees comes from those tests. The full suite is used
   only to score the final program ("intent pass"). Code that passes the visible tests
   but not the full suite is a silent failure: it looks finished and is wrong.
2. A programmer who knows what they mean. The simulated programmer privately holds
   the full specification but typed only the vibe prompt. How much of that intent
   reaches the model depends on the protocol:
     slot_machine       vibecoder: pastes whatever their tests report, never volunteers detail
     attentive          reads every attempt and writes one clarifying sentence (upper bound)
     retry_budget       P1, k attempts on visible feedback, then a handoff the programmer fills
     hidden_best_of_n   P2, best of n by visible tests, behavioural diff over visible tests
     test_gated_reveal  P3, gated on visible tests; the programmer vets each diagnosis
     typed_holes_patch  P4, the programmer fills the holes
     typed_holes_fixed  P4 + hole requests: the programmer may ask for a decision fixed in the
                        boilerplate to become a hole, and the agent re-scaffolds once

The simulated programmer is a model given that role (calls tagged human_proxy_*),
not a person. That modelling assumption is stated in the paper.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from types import SimpleNamespace

from tasks import Task
from .codeutil import code_lines, extract_code, merge_fills
from .llm_client import LLMResponse
from .metrics import PASS, classify
from .patches import Ctx, Session, _scaffold, behavioural_diff, check_invariants_against, is_code_free
from .prompts import (DECOMPOSE, DIAGNOSIS, HOLE_FILL_FEEDBACK, HOLE_FILL_INTENT, HOLE_REQUEST_OPTION,
                      MY_TESTS_MESSAGE, RESCAFFOLD, REVIEW_ATTEMPT, REVIEW_DIAGNOSIS, SKELETON, SYSTEM_CODER,
                      SYSTEM_DIAGNOSER, SYSTEM_PROGRAMMER, dialogue_prompt, error_paste_prompt, refined_prompt,
                      task_prompt)
from .sandbox import ExecResult, run_tests

N_VISIBLE = 3
MAX_CLARIFICATION_WORDS = 40
VARIANTS = ("slot_machine", "attentive", "retry_budget", "hidden_best_of_n", "test_gated_reveal",
            "typed_holes_patch", "typed_holes_fixed")


def visible_task(task: Task, n: int = N_VISIBLE) -> Task:
    """The programmer's own tests: the first n tests of the task."""
    return replace(task, tests=task.tests[:n])


@dataclass
class Check:
    """A program checked against the programmer's tests and against the full intent."""
    code: str
    vis: ExecResult
    full: ExecResult
    latency_s: float = 0.0   # model latency of the generation that produced this code

    @property
    def vis_outcome(self) -> str:
        return classify(self.vis.n_pass, self.vis.n_total, self.vis.syntax_ok)

    @property
    def full_outcome(self) -> str:
        return classify(self.full.n_pass, self.full.n_total, self.full.syntax_ok)

    @property
    def vis_pass(self) -> bool:
        return self.vis.all_pass

    @property
    def full_pass(self) -> bool:
        return self.full.all_pass


def check(task: Task, code: str) -> Check:
    return Check(code, run_tests(code, visible_task(task)), run_tests(code, task))


@dataclass
class RSession(Session):
    human_turns: int = 0          # times the programmer had to act (paste, review, clarify, fill, request)
    shown_lines: int = 0          # lines of code or text put in front of the programmer
    final_visible_pass: bool = False

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update(intent_pass=self.final_pass, visible_pass=self.final_visible_pass,
                 silent_failure=self.final_visible_pass and not self.final_pass,
                 human_turns=self.human_turns, shown_lines=self.shown_lines, n_visible=N_VISIBLE)
        return d


def _ev(s: RSession, kind: str, chk: Check, **kw) -> None:
    """Record what the programmer sees (visible-test result) plus the held-out truth."""
    s.event(kind, chk.vis_outcome, chk.vis, intent_outcome=chk.full_outcome, intent_n_pass=chk.full.n_pass,
            intent_n_total=chk.full.n_total, intent_failed=[o.name for o in chk.full.failed()], **kw)


def _finish(s: RSession, chk: Check | None) -> None:
    if chk is None:
        return
    s.final_code = chk.code
    s.final_pass = chk.full_pass
    s.final_visible_pass = chk.vis_pass
    s.total_lines = code_lines(chk.code)


def _gen(ctx: Ctx, s: RSession, prompt: str, sample: int, tag: str, parallel: bool = False) -> Check:
    resp = ctx.client.complete(prompt, SYSTEM_CODER, sample=sample, tag=tag)
    chk = check(s.task, extract_code(resp.text))
    chk.latency_s = resp.latency_s
    s.agent(resp, chk.vis.wall_s + chk.full.wall_s, parallel=parallel)
    return chk


def _ask_programmer(ctx: Ctx, s: RSession, prompt: str, sample: int, tag: str) -> str:
    resp: LLMResponse = ctx.client.complete(prompt, SYSTEM_PROGRAMMER, sample=sample, tag=f"human_proxy_{tag}")
    s.proxy(resp)
    s.human_turns += 1
    return resp.text.strip()


def is_accept(text: str) -> bool:
    words = re.sub(r"[^A-Za-z ]", " ", text).split()
    return bool(words) and words[0].upper() == "ACCEPT" and len(words) <= 3


def clip_words(text: str, n: int = MAX_CLARIFICATION_WORDS) -> str:
    words = " ".join(text.split()).strip('"').split()
    return " ".join(words[:n])


_REQUEST = re.compile(r"^\s*REQUEST_HOLE:\s*(.+)$", re.M)


def parse_hole_request(text: str) -> str | None:
    if "```" in text:
        return None
    m = _REQUEST.search(text)
    return clip_words(m.group(1)) if m else None


def _intent(task: Task) -> dict:
    return {"vibe": task_prompt(task, "vibe"), "spec": task_prompt(task, "spec")}


def _report(task: Task, chk: Check) -> str:
    if chk.vis_pass:
        return f"{chk.vis.n_pass} passed"
    return chk.vis.failure_report(visible_task(task))


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------
def slot_machine(ctx: Ctx, task: Task, j: int, max_turns: int = 5) -> RSession:
    """Vibecoder: paste whatever the programmer's tests report until they pass."""
    s = RSession("slot_machine", task, j)
    history, chk = [], None
    for t in range(1, max_turns + 1):
        prompt = task_prompt(task, ctx.style) if t == 1 else error_paste_prompt(task, history, ctx.style)
        chk = _gen(ctx, s, prompt, j, f"blind:{ctx.style}" if t == 1 else "p3r_error_paste")
        _ev(s, "code", chk, turn=t)
        s.shown_lines += code_lines(chk.code)
        if chk.vis_pass:
            break
        s.human_turns += 1  # copies the test output back
        history.append((chk.code, _report(task, chk)))
    s.passive_retries = len(s.events) - 1
    s.model_only_pass = bool(chk and chk.full_pass)
    _finish(s, chk)
    return s


def attentive(ctx: Ctx, task: Task, j: int, max_turns: int = 5) -> RSession:
    """Upper bound: the programmer reads every attempt and says what to change."""
    s = RSession("attentive", task, j)
    history, chk, clarifications = [], None, []
    for t in range(1, max_turns + 1):
        prompt = task_prompt(task, ctx.style) if t == 1 else dialogue_prompt(task, history, ctx.style)
        chk = _gen(ctx, s, prompt, j, f"blind:{ctx.style}" if t == 1 else "p3r_attentive")
        _ev(s, "code", chk, turn=t)
        s.shown_lines += code_lines(chk.code)
        s.review_items += 1
        reply = _ask_programmer(ctx, s, REVIEW_ATTEMPT.format(**_intent(task), code=chk.code.rstrip(),
                                                              report=_report(task, chk)), j, "attentive")
        accepted = is_accept(reply)
        s.event("review", None, accepted=accepted, text=None if accepted else clip_words(reply), turn=t)
        if accepted and chk.vis_pass:
            break
        msg = "" if chk.vis_pass else MY_TESTS_MESSAGE.format(report=_report(task, chk))
        if accepted:
            msg += "Please fix it."
            s.passive_retries += 1
        else:
            clar = clip_words(reply)
            clarifications.append(clar)
            s.decision_points += 1
            msg += clar
        history.append((chk.code, msg))
    s.extra["clarifications"] = clarifications
    _finish(s, chk)
    return s


# ---------------------------------------------------------------------------
# Typed-hole handoffs (P1, P4) with a programmer who knows the intent
# ---------------------------------------------------------------------------
def _fill(ctx: Ctx, s: RSession, skeleton: str, holes: list[str], rounds: int, sample: int, tag: str,
          allow_request: bool) -> tuple[Check | None, int, str | None]:
    vis = visible_task(s.task)
    fills_src, report, chk, n_lines = "", "", None, 0
    for r in range(1, rounds + 1):
        feedback = HOLE_FILL_FEEDBACK.format(fills=fills_src, report=report) if r > 1 else ""
        option = HOLE_REQUEST_OPTION if (allow_request and r == 1) else ""
        reply = _ask_programmer(ctx, s, HOLE_FILL_INTENT.format(**_intent(s.task), skeleton=skeleton,
                                                                feedback=feedback, request_option=option),
                                sample, tag)
        if option:
            req = parse_hole_request(reply)
            if req:
                s.event("hole_request", None, text=req, round=r)
                return None, 0, req
        program, kept, n_lines = merge_fills(skeleton, extract_code(reply), holes)
        chk = check(s.task, program)
        _ev(s, "human_fill", chk, round=r, fill_lines=n_lines)
        if chk.vis_pass:
            break
        fills_src, report = kept, chk.vis.failure_report(vis)
    return chk, n_lines, None


def _complete_with_holes(ctx: Ctx, s: RSession, skeleton: str, holes: list[str], rounds: int, sample: int,
                         tag: str, allow_request: bool = False) -> None:
    s.shown_lines += code_lines(skeleton)
    if not holes:  # non-compliant scaffold: a complete program, shown as a pull
        chk = check(s.task, skeleton)
        _ev(s, "code", chk, note="scaffold had no holes")
        s.model_only_pass = chk.full_pass
        _finish(s, chk)
        return
    chk, n_lines, req = _fill(ctx, s, skeleton, holes, rounds, sample, tag, allow_request)
    if req is not None:
        s.extra["hole_request"] = req
        s.decision_points += 1
        skeleton, holes = _scaffold(ctx, s, RESCAFFOLD.format(request=task_prompt(s.task, ctx.style),
                                                              skeleton=skeleton.rstrip(), req=req),
                                    sample, "p3r_rescaffold")
        s.events[-1]["rescaffold"] = True
        s.shown_lines += code_lines(skeleton)
        if not holes:
            chk = check(s.task, skeleton)
            _ev(s, "code", chk, note="scaffold had no holes")
            _finish(s, chk)
            return
        chk, n_lines, _ = _fill(ctx, s, skeleton, holes, rounds, sample, tag, allow_request=False)
    s.decision_points += len(holes)
    _finish(s, chk)
    s.human_lines = n_lines
    s.invariants_hold_final = check_invariants_against(chk.code, s.task, s.invariants) if chk else 0


def retry_budget(ctx: Ctx, task: Task, j: int, k: int = 1, rounds: int = 2) -> RSession:
    """P1: k automatic attempts on visible feedback, then a decomposition handoff."""
    s = RSession("retry_budget", task, j)
    history, chk = [], None
    for t in range(1, k + 1):
        prompt = task_prompt(task, ctx.style) if t == 1 else error_paste_prompt(task, history, ctx.style)
        chk = _gen(ctx, s, prompt, j, f"blind:{ctx.style}" if t == 1 else "p3r_error_paste")
        _ev(s, "code", chk, turn=t)
        s.shown_lines += code_lines(chk.code)
        if chk.vis_pass:
            s.passive_retries = t - 1
            s.model_only_pass = chk.full_pass
            _finish(s, chk)
            return s
        s.human_turns += 1
        history.append((chk.code, _report(task, chk)))
    s.passive_retries = k - 1
    s.extra["handoff"] = True
    prompt = DECOMPOSE.format(request=task_prompt(task, ctx.style), code=chk.code.rstrip(),
                              report=_report(task, chk))
    skeleton, holes = _scaffold(ctx, s, prompt, j, "p1_decompose")
    _complete_with_holes(ctx, s, skeleton, holes, rounds, j, "p3r_p1_fill")
    return s


def typed_holes(ctx: Ctx, task: Task, j: int, rounds: int = 3, requests: bool = False) -> RSession:
    """P4 (and P4 + hole requests): spec-first skeleton, the programmer fills the holes."""
    s = RSession("typed_holes_fixed" if requests else "typed_holes_patch", task, j)
    skeleton, holes = _scaffold(ctx, s, SKELETON.format(request=task_prompt(task, ctx.style)), j, "p4_skeleton")
    _complete_with_holes(ctx, s, skeleton, holes, rounds, j, "p3r_p4_fill", allow_request=requests)
    return s


# ---------------------------------------------------------------------------
# P2 and P3 on visible feedback
# ---------------------------------------------------------------------------
def hidden_best_of_n(ctx: Ctx, task: Task, j: int, n: int = 5, rounds: int = 3) -> RSession:
    s = RSession("hidden_best_of_n", task, j)
    vis = visible_task(task)
    history, best_chk = [], None
    for r in range(1, rounds + 1):
        if r == 1:
            prompt, samples, tag = task_prompt(task, ctx.style), [(j + i) % ctx.pool_size for i in range(n)], \
                f"blind:{ctx.style}"
        else:
            prompt, samples, tag = error_paste_prompt(task, history, ctx.style), list(range(n)), "p3r_p2_round"
        cands = [_gen(ctx, s, prompt, smp, tag, parallel=True) for smp in samples]
        s.agent_latency_s += max(c.latency_s + c.vis.wall_s + c.full.wall_s for c in cands)  # parallel
        best = max(range(n), key=lambda i: (cands[i].vis.n_pass, -i))
        best_chk = cands[best]
        diff = behavioural_diff([SimpleNamespace(result=c.vis) for c in cands], best, vis)
        s.review_items += len(diff["disagree"])
        _ev(s, "best_of_n", best_chk, round=r, diff=diff["text"], distinct=diff["distinct"],
            hidden_outcomes=[c.vis_outcome for c in cands], hidden_intent_outcomes=[c.full_outcome for c in cands])
        s.shown_lines += code_lines(best_chk.code) + diff["text"].count("\n") + 1
        if best_chk.vis_pass:
            break
        s.human_turns += 1
        history.append((best_chk.code, _report(task, best_chk)))
    s.passive_retries = sum(e["kind"] == "best_of_n" for e in s.events) - 1
    s.model_only_pass = bool(best_chk and best_chk.full_pass)
    _finish(s, best_chk)
    return s


def test_gated_reveal(ctx: Ctx, task: Task, j: int, k: int = 3) -> RSession:
    s = RSession("test_gated_reveal", task, j)
    clar: list[str] = []
    hints_code_free, accepted = [], []
    for t in range(1, k + 1):
        prompt = refined_prompt(task, clar, ctx.style)
        chk = _gen(ctx, s, prompt, j, f"blind:{ctx.style}" if t == 1 else "p3r_p3_regen")
        if chk.vis_pass:
            _ev(s, "revealed", chk, turn=t)
            s.shown_lines += code_lines(chk.code)
            s.model_only_pass = chk.full_pass
            _finish(s, chk)
            break
        s.event("hidden_attempt", "hidden", None, turn=t, true_outcome=chk.vis_outcome, n_pass=chk.vis.n_pass,
                n_total=chk.vis.n_total, intent_outcome=chk.full_outcome, intent_n_pass=chk.full.n_pass,
                intent_n_total=chk.full.n_total)
        resp = ctx.client.complete(DIAGNOSIS.format(request=prompt, report=_report(task, chk),
                                                    code=chk.code.rstrip()), SYSTEM_DIAGNOSER, sample=j,
                                   tag="p3r_diagnosis")
        s.agent(resp)
        hint = " ".join(resp.text.strip().split())
        hints_code_free.append(is_code_free(hint))
        s.event("diagnosis", None, text=hint, code_free=hints_code_free[-1], turn=t)
        s.shown_lines += 1
        s.review_items += 1
        if t < k:
            reply = _ask_programmer(ctx, s, REVIEW_DIAGNOSIS.format(**_intent(task), hint=hint), j, "p3_review")
            ok = is_accept(reply)
            accepted.append(ok)
            clar.append(hint if ok else clip_words(reply))
            s.event("diagnosis_review", None, accepted=ok, text=None if ok else clar[-1], turn=t)
            s.decision_points += 1
    s.extra.update(clarifications=clar, hints_code_free=hints_code_free, diagnoses_accepted=accepted)
    return s


test_gated_reveal.__test__ = False  # not a pytest test despite the name


def run_variant(ctx: Ctx, variant: str, task: Task, j: int, k: int) -> RSession:
    if variant == "slot_machine":
        return slot_machine(ctx, task, j, max_turns=5)
    if variant == "attentive":
        return attentive(ctx, task, j, max_turns=5)
    if variant == "retry_budget":
        return retry_budget(ctx, task, j, k=1)
    if variant == "hidden_best_of_n":
        return hidden_best_of_n(ctx, task, j, n=5, rounds=k)
    if variant == "test_gated_reveal":
        return test_gated_reveal(ctx, task, j, k=k)
    if variant == "typed_holes_patch":
        return typed_holes(ctx, task, j, rounds=k, requests=False)
    if variant == "typed_holes_fixed":
        return typed_holes(ctx, task, j, rounds=k, requests=True)
    raise ValueError(variant)
