"""Benchmark task registry."""
from __future__ import annotations

from .schema import Task, TestCase
from dataclasses import replace

from . import humaneval_tasks, mbpp_tasks, original_tasks
from .vibe_prompts import VIBE_PROMPTS

_SUITES = [humaneval_tasks.TASKS, mbpp_tasks.TASKS, original_tasks.TASKS]


def load_tasks(suite: str | None = None) -> list[Task]:
    tasks = [replace(t, vibe_prompt=VIBE_PROMPTS[t.task_id]) for group in _SUITES for t in group]
    if suite:
        tasks = [t for t in tasks if t.suite == suite]
    return tasks


def get_task(task_id: str) -> Task:
    for t in load_tasks():
        if t.task_id == task_id:
            return t
    raise KeyError(task_id)


__all__ = ["Task", "TestCase", "load_tasks", "get_task"]
