import pytest

from harness.sandbox import run_tests, ExecResult
from tasks import get_task, load_tasks


@pytest.mark.parametrize("task", load_tasks(), ids=lambda t: t.task_id)
def test_reference_passes_in_sandbox(task):
    r = run_tests(task.reference, task)
    assert r.all_pass, r.failure_report(task)
    assert r.frac == 1.0


def test_syntax_error_counts_as_zero():
    task = get_task("mbpp_remove_occ")
    r = run_tests("def remove_occ(s, ch)\n    return s", task)
    assert r.n_pass == 0 and not r.syntax_ok
    assert r.load_error[0] == "SyntaxError"
    assert "ERROR collecting" in r.failure_report(task)


def test_partial_credit_and_rewritten_assert():
    task = get_task("he_fix_spaces")
    # Classic near-miss: forgets the "more than two spaces -> dash" rule.
    r = run_tests("def fix_spaces(text):\n    return text.replace(' ', '_')", task)
    assert 0 < r.n_pass < r.n_total
    failing = {o.name: o for o in r.failed()}
    assert "triple_run" in failing
    msg = failing["triple_run"].message
    assert "got:" in msg and "expected:" in msg and "'_Example-3'" in msg


def test_per_test_timeout_isolates_infinite_loop():
    task = get_task("mbpp_sort_matrix")
    code = (
        "def sort_matrix(m):\n"
        "    if m == []:\n"
        "        while True: pass\n"
        "    return [list(r) for r in sorted(m, key=sum)]\n"
    )
    r = run_tests(code, task, per_test_timeout=0.5)
    outcome = {o.name: o for o in r.outcomes}
    assert outcome["empty"].error_type == "Timeout"
    assert r.n_pass == r.n_total - 1


def test_candidate_cannot_swallow_timeout():
    task = get_task("mbpp_sort_matrix")
    code = (
        "def sort_matrix(m):\n"
        "    while True:\n"
        "        try:\n"
        "            pass\n"
        "        except Exception:\n"
        "            pass\n"
    )
    r = run_tests(code, task, per_test_timeout=0.2, suite_timeout=8)
    assert r.n_pass == 0
    assert all(o.error_type == "Timeout" for o in r.outcomes)


def test_sys_exit_at_import_is_contained():
    task = get_task("mbpp_remove_occ")
    r = run_tests("import sys\nsys.exit(3)", task)
    assert r.n_pass == 0 and r.load_error[0] == "SystemExit"


def test_roundtrip_serialization():
    task = get_task("mbpp_remove_occ")
    r = run_tests(task.reference, task)
    r2 = ExecResult.from_dict(r.to_dict())
    assert r2.pass_vector() == r.pass_vector() and r2.n_pass == r.n_pass
