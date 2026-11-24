"""Validate the benchmark itself: every reference solution must pass its
own suite, and suites must be granular enough for partial credit."""
import pytest

from tasks import load_tasks


def run_reference_inprocess(task):
    ns = {"__name__": "candidate", "__source__": task.reference}
    exec(compile(task.reference, f"<{task.task_id}>", "exec"), ns)
    if task.test_prelude:
        exec(compile(task.test_prelude, "<prelude>", "exec"), ns)
    failures = []
    for tc in task.tests:
        try:
            exec(compile(tc.code, f"<{task.task_id}:{tc.name}>", "exec"), dict(ns))
        except Exception as e:  # noqa: BLE001
            failures.append((tc.name, repr(e)))
    return failures


@pytest.mark.parametrize("task", load_tasks(), ids=lambda t: t.task_id)
def test_reference_passes(task):
    assert run_reference_inprocess(task) == []


@pytest.mark.parametrize("task", load_tasks(), ids=lambda t: t.task_id)
def test_suite_granularity(task):
    assert 8 <= task.n_tests <= 10
    assert len({tc.name for tc in task.tests}) == task.n_tests


def test_unique_ids():
    ids = [t.task_id for t in load_tasks()]
    assert len(ids) == len(set(ids))


def test_suite_composition():
    tasks = load_tasks()
    assert len(tasks) == 30
    for suite in ("humaneval", "mbpp", "original"):
        assert len(load_tasks(suite)) == 10


@pytest.mark.parametrize("task", load_tasks(), ids=lambda t: t.task_id)
def test_empty_candidate_fails_everything(task):
    """Every test must actually exercise the candidate (no vacuous tests)."""
    ns = {"__name__": "candidate", "__source__": ""}
    if task.test_prelude:
        exec(task.test_prelude, ns)
    for tc in task.tests:
        with pytest.raises(Exception):
            exec(compile(tc.code, tc.name, "exec"), dict(ns))


@pytest.mark.parametrize("task", load_tasks(), ids=lambda t: t.task_id)
def test_vibe_prompt_names_api_and_is_terse(task):
    assert task.vibe_prompt
    for ep in task.entry_points:
        if ep not in ("ParseError",):
            assert ep in task.vibe_prompt, ep
    assert len(task.vibe_prompt) < 0.6 * len(task.prompt)
