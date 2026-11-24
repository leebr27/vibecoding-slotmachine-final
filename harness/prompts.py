"""Prompt templates. Kept in one place so the paper can quote them exactly."""
from __future__ import annotations

SYSTEM_CODER = (
    "You are a coding assistant. Reply with exactly one Python code block containing the "
    "complete, self-contained implementation (every requested function or class, plus any "
    "imports). Do not include tests, usage examples, or any explanation outside the code block."
)

VIBE_FIX_MESSAGE = "I ran the tests and got this:\n```\n{report}\n```\nPlease fix it."


def task_prompt(task, style: str = "vibe") -> str:
    """`vibe`: the terse request a user types. `spec`: the full specification."""
    if style == "vibe":
        return task.vibe_prompt.strip()
    if style == "spec":
        return task.prompt.strip()
    raise ValueError(style)


def error_paste_prompt(task, history: list[tuple[str, str]], style: str = "vibe") -> str:
    """Transcript of a passive 'paste the error, ask for a fix' session.

    `history` is a list of (code, failure_report) pairs, oldest first.
    """
    parts = ["Below is our conversation so far. Continue it by replying to the last user message.\n",
             "[user]\n" + task_prompt(task, style)]
    for code, report in history:
        parts.append("[assistant]\n```python\n" + code.rstrip() + "\n```")
        parts.append("[user]\n" + VIBE_FIX_MESSAGE.format(report=report))
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Patch prompts
# ---------------------------------------------------------------------------
SYSTEM_DIAGNOSER = (
    "You are a code reviewer helping a programmer sharpen their own specification. "
    "You never write or quote code."
)

DIAGNOSIS = """The programmer asked an AI assistant for:
{request}

The assistant produced a candidate implementation. It is hidden from the programmer. It was run against the programmer's tests:
```
{report}
```
Hidden candidate (for your reference only):
```python
{code}
```
In at most two sentences, and without writing any code, state the requirement that the candidate gets wrong, phrased as a clarification the programmer could add to their request (for example: "An empty input should return an empty list rather than None.")."""


def refined_prompt(task, clarifications: list[str], style: str = "vibe") -> str:
    if not clarifications:
        return task_prompt(task, style)
    return task_prompt(task, style) + "\n\nClarifications:\n" + "\n".join(f"- {c}" for c in clarifications)


SYSTEM_SCAFFOLDER = (
    "You are a pair programmer who writes scaffolding and boilerplate and deliberately leaves the core "
    "decisions to the human programmer."
)

_HOLE_RULES = """Do NOT write the full solution. Write a skeleton program for the human to complete:
1. Implement the complete public API requested above (exact names and signatures) and all boilerplate
   (input handling, data structures, iteration, formatting), delegating every core algorithmic or
   policy decision to helper functions whose names start with `hole_`.
2. Each hole is a module-level function with type hints and a docstring that states precisely what it
   must return. Its body must be only `raise NotImplementedError`. Use between 1 and 4 holes.
3. Add a function `check_invariants()` containing 4 to 8 assert statements about the intended
   behaviour of the PUBLIC API only (concrete input/output examples and properties, including edge
   cases). Do not call it anywhere.
Reply with exactly one Python code block."""

SKELETON = "{request}\n\n" + _HOLE_RULES

DECOMPOSE = """{request}

The retry budget for automatic attempts is exhausted. The last automatic attempt was:
```python
{code}
```
and it failed these tests:
```
{report}
```
Do not attempt another full solution. Hand control back to the programmer instead. You may reuse
working parts of the last attempt as boilerplate, but every decision implicated by the failures above
must live inside a hole.

""" + _HOLE_RULES

SYSTEM_HOLE_FILLER = (
    "You are the human programmer completing a skeleton written by your AI pair programmer. "
    "You write only the bodies of the hole_ functions."
)

HOLE_FILL = """Task:
{request}

Skeleton written by the AI pair programmer:
```python
{skeleton}
```
{feedback}Write complete implementations of every `hole_` function, keeping their names and signatures.
Reply with exactly one Python code block containing only those functions and any imports they need."""

HOLE_FILL_FEEDBACK = """Your previous hole implementations:
```python
{fills}
```
Running the tests on the completed program gave:
```
{report}
```
"""


# ---------------------------------------------------------------------------
# Phase 3 (realistic feedback): the simulated programmer knows what they mean
# ---------------------------------------------------------------------------
# The programmer typed only the vibe prompt but privately holds the full
# specification. They see feedback only from their own few visible tests.

SYSTEM_PROGRAMMER = (
    "You are role-playing a programmer who asked an AI assistant for code. You know exactly what you "
    "want, but you only typed a short request. Answer in the exact format you are asked for."
)

_INTENT = """You typed this short request to the AI assistant:
{vibe}

What you actually want (the assistant has NOT seen this):
{spec}
"""

REVIEW_ATTEMPT = _INTENT + """
The assistant replied with this code:
```python
{code}
```
You ran your own tests on it:
```
{report}
```
Read the code and check it against what you actually want. If it does what you want, reply with exactly:
ACCEPT
Otherwise reply with one sentence of at most 30 words, without any code, telling the assistant what to change."""

REVIEW_DIAGNOSIS = _INTENT + """
Your tests failed, so the assistant hid its code and instead suggests adding this clarification to your request:
"{hint}"
If the clarification matches what you want, reply with exactly:
ACCEPT
Otherwise reply with one corrected sentence of at most 30 words, without any code, stating the requirement as you intend it."""

HOLE_FILL_INTENT = _INTENT + """
Skeleton written by your AI pair programmer:
```python
{skeleton}
```
{feedback}{request_option}Write complete implementations of every `hole_` function so that the program does what you actually want, keeping their names and signatures.
Reply with exactly one Python code block containing only those functions and any imports they need."""

HOLE_REQUEST_OPTION = """Before filling the holes, check the code OUTSIDE the hole_ functions. If it already fixes a decision
that matters for what you want, so that no way of filling the holes could get it right, do not fill the
holes; reply instead with a single line:
REQUEST_HOLE: <one sentence, without code, naming that decision>

"""

RESCAFFOLD = """{request}

Your previous skeleton:
```python
{skeleton}
```
The programmer reviewed it and asked for this decision to be left to them instead of being fixed in the
boilerplate:
{req}

Write a new skeleton in which that decision lives inside a hole.

""" + _HOLE_RULES

MY_TESTS_MESSAGE = "I ran my tests and got this:\n```\n{report}\n```\n"


def dialogue_prompt(task, history: list[tuple[str, str]], style: str = "vibe") -> str:
    """Conversation transcript where each user turn is free text (an attentive programmer).

    `history` is a list of (code, user_message) pairs, oldest first.
    """
    parts = ["Below is our conversation so far. Continue it by replying to the last user message.\n",
             "[user]\n" + task_prompt(task, style)]
    for code, msg in history:
        parts.append("[assistant]\n```python\n" + code.rstrip() + "\n```")
        parts.append("[user]\n" + msg.strip())
    return "\n\n".join(parts)
