"""Task schema for the benchmark.

A task is a natural-language specification (what the model sees), a hidden
reference solution (used only to validate the test suite and to check
model-written invariants), and a list of granular test cases. Each test case
is a small, self-contained snippet of Python executed against the candidate
module's namespace, so partial pass rates p/T are meaningful.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TestCase:
    name: str
    code: str


@dataclass(frozen=True)
class Task:
    task_id: str
    suite: str  # "humaneval" | "mbpp" | "original"
    title: str
    entry_points: tuple[str, ...]
    prompt: str
    reference: str
    tests: tuple[TestCase, ...]
    source_note: str = ""
    # Code run before every test case (helpers shared by a suite's tests).
    test_prelude: str = ""
    # Terse request a vibecoder would type (see tasks/vibe_prompts.py).
    vibe_prompt: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def n_tests(self) -> int:
        return len(self.tests)


def T(name: str, code: str) -> TestCase:
    """Shorthand constructor used by the task files."""
    return TestCase(name=name, code=code.strip())
