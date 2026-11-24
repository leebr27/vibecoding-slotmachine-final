"""Helpers for pulling code out of model responses and measuring it."""
from __future__ import annotations

import ast
import re

_FENCE = re.compile(r"```(?:python|py|python3)?[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_code(text: str) -> str:
    """Return the Python program contained in a model response.

    Prefers fenced code blocks (concatenating several, as a user copy-pasting
    every block would); falls back to the raw text if it parses as Python.
    """
    blocks = _FENCE.findall(text or "")
    if blocks:
        return "\n\n".join(b.strip("\n") for b in blocks).strip() + "\n"
    raw = (text or "").strip()
    if raw.startswith("```"):  # unterminated fence
        raw = raw.split("\n", 1)[1] if "\n" in raw else ""
    return raw + "\n" if raw else ""


def parses(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def code_lines(code: str) -> int:
    """Non-blank, non-comment source lines."""
    return sum(1 for ln in code.splitlines() if ln.strip() and not ln.strip().startswith("#"))


# ---------------------------------------------------------------------------
# Typed-hole skeletons
# ---------------------------------------------------------------------------
HOLE_PREFIX = "hole_"


def _is_unfilled(fn: ast.FunctionDef) -> bool:
    body = list(fn.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) \
            and isinstance(body[0].value.value, str):
        body = body[1:]
    if len(body) != 1:
        return False
    st = body[0]
    if isinstance(st, ast.Raise) and st.exc is not None:
        exc = st.exc.func if isinstance(st.exc, ast.Call) else st.exc
        return isinstance(exc, ast.Name) and exc.id == "NotImplementedError"
    return isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant) and st.value.value is Ellipsis


def find_holes(code: str) -> list[str]:
    """Names of unfilled module-level `hole_*` functions."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    return [n.name for n in tree.body if isinstance(n, ast.FunctionDef)
            and n.name.startswith(HOLE_PREFIX) and _is_unfilled(n)]


def strip_toplevel_calls(code: str) -> str:
    """Drop bare top-level expression statements (e.g. a stray `check_invariants()`)."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return code
    tree.body = [n for n in tree.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Call))]
    return ast.unparse(tree) + "\n"


def extract_invariants(code: str, fn_name: str = "check_invariants") -> list[str]:
    """Each assert in `fn_name`, prefixed by the non-assert setup statements before it."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == fn_name:
            setup, out = [], []
            for st in n.body:
                if isinstance(st, ast.Expr) and isinstance(st.value, ast.Constant):
                    continue  # docstring
                if isinstance(st, ast.Assert):
                    out.append("\n".join(setup + [ast.unparse(st)]))
                else:
                    setup.append(ast.unparse(st))
            return out
    return []


def _toplevel_names(tree: ast.Module) -> set[str]:
    names = set()
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(n.name)
        elif isinstance(n, ast.Assign):
            names.update(t.id for t in n.targets if isinstance(t, ast.Name))
        elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
            names.add(n.target.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            names.update((a.asname or a.name).split(".")[0] for a in n.names)
    return names


def merge_fills(skeleton: str, fills: str, holes: list[str]) -> tuple[str, str, int]:
    """Splice the programmer's hole implementations into the skeleton.

    Ownership boundary: from `fills` we keep imports, the `hole_*` functions,
    and NEW top-level helper definitions (functions, classes, constants) whose
    names the skeleton does not already define. Anything that would redefine
    a skeleton-owned name is dropped, so the programmer edits holes, not the
    agent's code. `from __future__` imports are dropped (they are only legal at
    the top of a file). Returns (program, kept_fill_source, n_fill_lines)."""
    try:
        tree = ast.parse(fills)
    except SyntaxError:
        return skeleton, "", 0
    try:
        owned = _toplevel_names(ast.parse(skeleton)) - set(holes)
    except SyntaxError:
        owned = set()
    kept = []
    for n in tree.body:
        if isinstance(n, ast.ImportFrom) and n.module == "__future__":
            continue
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            kept.append(n)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if n.name in holes or n.name not in owned:
                kept.append(n)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            if all(isinstance(t, ast.Name) and t.id not in owned for t in targets):
                kept.append(n)
    src = "\n\n".join(ast.unparse(n) for n in kept)
    program = skeleton.rstrip() + "\n\n\n# ---- holes filled by the programmer ----\n" + src + "\n"
    return program, src, code_lines(src)
