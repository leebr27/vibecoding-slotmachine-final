"""Ten algorithmic tasks adapted from HumanEval (Chen et al., 2021).

Each task keeps the HumanEval entry-point name and core semantics, but the
specification text is rewritten and the test suites are our own: 8-10
granular assertions per task (HumanEval's originals often bundle every check
into one `check` function, which hides partial correctness).
"""
from .schema import Task, T

TASKS: list[Task] = []

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="he_make_palindrome",
    suite="humaneval",
    title="Shortest palindrome by appending",
    entry_points=("make_palindrome",),
    source_note="Adapted from HumanEval entry point make_palindrome.",
    prompt='''Write a Python function `make_palindrome(s: str) -> str`.

Return the shortest palindrome that begins with `s`, formed by appending
characters to the end of `s` only. The empty string maps to the empty string.
Comparison is case-sensitive.

Examples:
    make_palindrome("cat")  -> "catac"
    make_palindrome("cata") -> "catac"
''',
    reference='''
def make_palindrome(s):
    for i in range(len(s) + 1):
        suffix = s[i:]
        if suffix == suffix[::-1]:
            return s + s[:i][::-1]
    return s
''',
    tests=(
        T("empty", 'assert make_palindrome("") == ""'),
        T("single", 'assert make_palindrome("x") == "x"'),
        T("cat", 'assert make_palindrome("cat") == "catac"'),
        T("cata", 'assert make_palindrome("cata") == "catac"'),
        T("already_even", 'assert make_palindrome("abba") == "abba"'),
        T("already_odd", 'assert make_palindrome("abcba") == "abcba"'),
        T("two_distinct", 'assert make_palindrome("ab") == "aba"'),
        T("race", 'assert make_palindrome("race") == "racecar"'),
        T("case_sensitive", 'assert make_palindrome("Aa") == "AaA"'),
        T("long_suffix", 'assert make_palindrome("xyzaba") == "xyzabazyx"'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="he_fix_spaces",
    suite="humaneval",
    title="Replace spaces with underscores or dashes",
    entry_points=("fix_spaces",),
    source_note="Adapted from HumanEval entry point fix_spaces.",
    prompt='''Write a Python function `fix_spaces(text: str) -> str`.

Replace every space in `text` with an underscore, except that any run of
MORE THAN TWO consecutive spaces is replaced by a single dash "-".
A run of exactly two spaces becomes two underscores.

Examples:
    fix_spaces("Example 1")     -> "Example_1"
    fix_spaces(" Example   3")  -> "_Example-3"
''',
    reference='''
import re
def fix_spaces(text):
    def repl(m):
        run = m.group(0)
        return "-" if len(run) > 2 else "_" * len(run)
    return re.sub(r" +", repl, text)
''',
    tests=(
        T("no_spaces", 'assert fix_spaces("Example") == "Example"'),
        T("one_space", 'assert fix_spaces("Example 1") == "Example_1"'),
        T("leading_space", 'assert fix_spaces(" Example 2") == "_Example_2"'),
        T("triple_run", 'assert fix_spaces(" Example   3") == "_Example-3"'),
        T("trailing_space", 'assert fix_spaces("Mudasir Hanif ") == "Mudasir_Hanif_"'),
        T("double_runs", 'assert fix_spaces("Yellow Yellow  Dirty  Fellow") == "Yellow_Yellow__Dirty__Fellow"'),
        T("inner_triple", 'assert fix_spaces("Exa   mple") == "Exa-mple"'),
        T("leading_triple", 'assert fix_spaces("   Exa 1 2 2 mple") == "-Exa_1_2_2_mple"'),
        T("long_run", 'assert fix_spaces("a      b") == "a-b"'),
        T("empty", 'assert fix_spaces("") == ""'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="he_minpath",
    suite="humaneval",
    title="Lexicographically minimal grid path",
    entry_points=("minPath",),
    source_note="Adapted from HumanEval entry point minPath.",
    prompt='''Write a Python function `minPath(grid: list[list[int]], k: int) -> list[int]`.

`grid` is an N x N grid (N >= 2) containing every integer from 1 to N*N exactly
once. A path of length k visits exactly k cells (not necessarily distinct):
it may start at any cell and each step moves to an edge-adjacent neighbour
(up, down, left, right; never off the grid). The value list of a path is the
list of values on the cells it visits, in order.

Return the value list of the path of length k whose value list is
lexicographically smallest. The answer is guaranteed to be unique.

Example:
    minPath([[1,2,3],[4,5,6],[7,8,9]], 3) -> [1, 2, 1]
''',
    reference='''
def minPath(grid, k):
    n = len(grid)
    best = None
    for i in range(n):
        for j in range(n):
            if grid[i][j] == 1:
                nb = []
                for di, dj in ((1,0),(-1,0),(0,1),(0,-1)):
                    a, b = i + di, j + dj
                    if 0 <= a < n and 0 <= b < n:
                        nb.append(grid[a][b])
                best = min(nb)
    return [1 if t % 2 == 0 else best for t in range(k)]
''',
    tests=(
        T("example", 'assert minPath([[1,2,3],[4,5,6],[7,8,9]], 3) == [1,2,1]'),
        T("k1", 'assert minPath([[5,9,3],[4,1,6],[7,8,2]], 1) == [1]'),
        T("center_one", 'assert minPath([[5,9,3],[4,1,6],[7,8,2]], 4) == [1,4,1,4]'),
        T("4x4", 'assert minPath([[1,2,3,4],[5,6,7,8],[9,10,11,12],[13,14,15,16]], 4) == [1,2,1,2]'),
        T("corner", 'assert minPath([[6,4,13,10],[5,7,12,1],[3,16,11,15],[8,14,9,2]], 7) == [1,10,1,10,1,10,1]'),
        T("2x2", 'assert minPath([[2,7],[4,1]], 5) == [1,4,1,4,1]'),
        T("odd_k", 'assert minPath([[8,14,9,2],[6,4,13,15],[5,7,1,12],[3,10,11,16]], 5) == [1,7,1,7,1]'),
        T("long_k", 'assert minPath([[11,8,7,2],[5,16,14,4],[9,3,15,6],[12,13,10,1]], 9) == [1,6,1,6,1,6,1,6,1]'),
        T("k2_side", 'assert minPath([[3,1],[2,4]], 2) == [1,3]'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="he_tri",
    suite="humaneval",
    title="Irregular Tribonacci sequence",
    entry_points=("tri",),
    source_note="Adapted from HumanEval entry point tri (integer variant).",
    prompt='''Write a Python function `tri(n: int) -> list[int]` for n >= 0.

The sequence t is defined by:
    t(0) = 1
    t(1) = 3
    t(k) = 1 + k // 2                          if k >= 2 and k is even
    t(k) = t(k - 1) + t(k - 2) + t(k + 1)      if k >= 3 and k is odd

(Note the odd case refers to t(k + 1), which is even and therefore defined
directly.) Return the list [t(0), t(1), ..., t(n)] of n + 1 integers.

Example:
    tri(3) -> [1, 3, 2, 8]
''',
    reference='''
def tri(n):
    def t(k):
        if k == 0:
            return 1
        if k == 1:
            return 3
        if k % 2 == 0:
            return 1 + k // 2
        return t(k - 1) + t(k - 2) + (1 + (k + 1) // 2)
    return [t(k) for k in range(n + 1)]
''',
    tests=(
        T("n0", 'assert tri(0) == [1]'),
        T("n1", 'assert tri(1) == [1, 3]'),
        T("n2", 'assert tri(2) == [1, 3, 2]'),
        T("n3", 'assert tri(3) == [1, 3, 2, 8]'),
        T("n4", 'assert tri(4) == [1, 3, 2, 8, 3]'),
        T("n5", 'assert tri(5) == [1, 3, 2, 8, 3, 15]'),
        T("n7", 'assert tri(7) == [1, 3, 2, 8, 3, 15, 4, 24]'),
        T("ints", 'assert all(isinstance(x, int) for x in tri(9))'),
        T("length", 'assert len(tri(20)) == 21'),
        T("n9_last", 'assert tri(9)[-1] == 35'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="he_is_nested",
    suite="humaneval",
    title="Nested bracket subsequence",
    entry_points=("is_nested",),
    source_note="Adapted from HumanEval entry point is_nested.",
    prompt='''Write a Python function `is_nested(s: str) -> bool`.

`s` contains only the characters "[" and "]". Return True if and only if
some subsequence of `s` (characters taken in order, not necessarily
contiguous) is a valid bracket sequence in which at least one pair of
brackets is nested inside another, i.e. the subsequence "[[]]" occurs.

Examples:
    is_nested("[[]]")     -> True
    is_nested("[][]")     -> False
    is_nested("[]]]][[[") -> False
''',
    reference='''
def is_nested(s):
    opens = [i for i, c in enumerate(s) if c == "["]
    closes = [i for i, c in enumerate(s) if c == "]"][::-1]
    cnt, i, l = 0, 0, len(closes)
    for idx in opens:
        if i < l and idx < closes[i]:
            cnt += 1
            i += 1
    return cnt >= 2
''',
    tests=(
        T("simple_nested", 'assert is_nested("[[]]") is True'),
        T("flat_pair", 'assert is_nested("[][]") is False'),
        T("single", 'assert is_nested("[]") is False'),
        T("noise_false", 'assert is_nested("[]]]]]]][[[[[]") is False'),
        T("nested_mixed", 'assert is_nested("[[][]]") is True'),
        T("prefix_nested", 'assert is_nested("[[]][[") is True'),
        T("deep", 'assert is_nested("[[[[]]]]") is True'),
        T("unbalanced_open", 'assert is_nested("[[]") is False'),
        T("noncontiguous", 'assert is_nested("[][][]]") is True'),
        T("empty", 'assert is_nested("") is False'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="he_file_name_check",
    suite="humaneval",
    title="File-name validation",
    entry_points=("file_name_check",),
    source_note="Adapted from HumanEval entry point file_name_check.",
    prompt='''Write a Python function `file_name_check(name: str) -> str` that
returns "Yes" if `name` is a valid file name and "No" otherwise.

A file name is valid if and only if ALL of the following hold:
  1. It contains at most three digit characters ("0"-"9") in total.
  2. It contains exactly one dot ".".
  3. The part before the dot is non-empty and starts with an ASCII Latin
     letter (a-z or A-Z).
  4. The part after the dot is exactly one of "txt", "exe", "dll"
     (case-sensitive).

Examples:
    file_name_check("example.txt") -> "Yes"
    file_name_check("1example.dll") -> "No"
''',
    reference='''
def file_name_check(name):
    if sum(c.isdigit() for c in name) > 3:
        return "No"
    parts = name.split(".")
    if len(parts) != 2:
        return "No"
    stem, ext = parts
    if ext not in ("txt", "exe", "dll"):
        return "No"
    if not stem or not (("a" <= stem[0] <= "z") or ("A" <= stem[0] <= "Z")):
        return "No"
    return "Yes"
''',
    tests=(
        T("valid", 'assert file_name_check("example.txt") == "Yes"'),
        T("leading_digit", 'assert file_name_check("1example.dll") == "No"'),
        T("three_digits_ok", 'assert file_name_check("a1b2c3.exe") == "Yes"'),
        T("four_digits", 'assert file_name_check("a1b2c3d4.exe") == "No"'),
        T("two_dots", 'assert file_name_check("my.file.txt") == "No"'),
        T("empty_stem", 'assert file_name_check(".txt") == "No"'),
        T("bad_ext", 'assert file_name_check("report.pdf") == "No"'),
        T("ext_case", 'assert file_name_check("report.TXT") == "No"'),
        T("non_ascii_letter", 'assert file_name_check("\\u00e9t\\u00e9.txt") == "No"'),
        T("no_dot", 'assert file_name_check("readme") == "No"'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="he_order_by_points",
    suite="humaneval",
    title="Sort by signed digit sum",
    entry_points=("order_by_points",),
    source_note="Adapted from HumanEval entry point order_by_points.",
    prompt='''Write a Python function `order_by_points(nums: list[int]) -> list[int]`.

Sort the integers in ascending order of their "signed digit sum". The signed
digit sum of a non-negative number is the sum of its decimal digits. For a
negative number, the FIRST (most significant) digit counts as negative and
the remaining digits count as positive; e.g. -12 -> -1 + 2 = 1 and
-305 -> -3 + 0 + 5 = 2. Numbers with equal signed digit sums keep their
original relative order.

Example:
    order_by_points([1, 11, -1, -11, -12]) -> [-1, -11, 1, -12, 11]
''',
    reference='''
def order_by_points(nums):
    def key(n):
        digits = [int(d) for d in str(abs(n))]
        if n < 0:
            digits[0] = -digits[0]
        return sum(digits)
    return sorted(nums, key=key)
''',
    tests=(
        T("example", 'assert order_by_points([1, 11, -1, -11, -12]) == [-1, -11, 1, -12, 11]'),
        T("empty", 'assert order_by_points([]) == []'),
        T("positives", 'assert order_by_points([45, 12, 3, 100]) == [100, 12, 3, 45]'),
        T("stable_ties", 'assert order_by_points([13, 31, 4, 22]) == [13, 31, 4, 22]'),
        T("negative_first_digit", 'assert order_by_points([-305, 2, -1]) == [-1, -305, 2]'),
        T("zero", 'assert order_by_points([0, -1, 1]) == [-1, 0, 1]'),
        T("neg_single_digits", 'assert order_by_points([-9, -3, -5]) == [-9, -5, -3]'),
        T("mixed", 'assert order_by_points([1234, 423, 463, 145, 2, 423, 423, 53, 6, 37, 3457, 3, 56, 0, 46]) == [0, 2, 3, 6, 53, 423, 423, 423, 1234, 145, 37, 46, 56, 463, 3457]'),
        T("neg_vs_pos_tie", 'assert order_by_points([-21, 3, -12]) == [-21, -12, 3]'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="he_do_algebra",
    suite="humaneval",
    title="Evaluate an operator/operand list",
    entry_points=("do_algebra",),
    source_note="Adapted from HumanEval entry point do_algebra.",
    prompt='''Write a Python function `do_algebra(operators: list[str], operands: list[int]) -> int`.

`operands` has length len(operators) + 1 and contains non-negative integers.
Each operator is one of "+", "-", "*", "//", "**". Build the expression
operands[0] op[0] operands[1] op[1] ... and return its value using standard
Python precedence and associativity ("**" binds tighter than "*" and "//",
which bind tighter than "+" and "-"; "**" is right-associative).
Do not use eval() or exec().

Example:
    do_algebra(["+", "*", "-"], [2, 3, 4, 5]) -> 9
''',
    reference='''
def do_algebra(operators, operands):
    # shunting-yard evaluation without eval()
    prec = {"+": 1, "-": 1, "*": 2, "//": 2, "**": 3}
    fns = {"+": lambda a, b: a + b, "-": lambda a, b: a - b, "*": lambda a, b: a * b,
           "//": lambda a, b: a // b, "**": lambda a, b: a ** b}
    out, ops = [operands[0]], []
    def apply(op):
        b = out.pop(); a = out.pop()
        out.append(fns[op](a, b))
    for op, val in zip(operators, operands[1:]):
        while ops and (prec[ops[-1]] > prec[op] or (prec[ops[-1]] == prec[op] and op != "**")):
            apply(ops.pop())
        ops.append(op)
        out.append(val)
    while ops:
        apply(ops.pop())
    return out[0]
''',
    tests=(
        T("example", 'assert do_algebra(["+", "*", "-"], [2, 3, 4, 5]) == 9'),
        T("single_op", 'assert do_algebra(["+"], [7, 8]) == 15'),
        T("precedence_mul", 'assert do_algebra(["-", "*"], [10, 2, 3]) == 4'),
        T("floor_div", 'assert do_algebra(["//", "+"], [7, 2, 1]) == 4'),
        T("pow_right_assoc", 'assert do_algebra(["**", "**"], [2, 3, 2]) == 512'),
        T("left_assoc_minus", 'assert do_algebra(["-", "-"], [10, 3, 2]) == 5'),
        T("left_assoc_div", 'assert do_algebra(["//", "//"], [100, 10, 3]) == 3'),
        T("pow_over_mul", 'assert do_algebra(["*", "**"], [3, 2, 3]) == 24'),
        T("mixed", 'assert do_algebra(["+", "**", "*", "-", "//"], [1, 2, 3, 4, 9, 2]) == 29'),
        T("no_eval", 'assert do_algebra(["*"], [6, 7]) == 42\nimport ast\ncalls = [n.func.id for n in ast.walk(ast.parse(__source__)) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]\nassert "eval" not in calls and "exec" not in calls'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="he_compare_one",
    suite="humaneval",
    title="Compare mixed numeric representations",
    entry_points=("compare_one",),
    source_note="Adapted from HumanEval entry point compare_one.",
    prompt='''Write a Python function `compare_one(a, b)`.

Each of `a` and `b` is an int, a float, or a string representing a real
number. A string may use either "." or "," as the decimal separator
(e.g. "2,3" means 2.3). Return whichever argument is numerically larger,
returned unchanged (same object type and value as it was passed in).
Return None if the two values are numerically equal.

Examples:
    compare_one(1, 2.5)     -> 2.5
    compare_one(1, "2,3")   -> "2,3"
    compare_one("1", 1)     -> None
''',
    reference='''
def compare_one(a, b):
    def num(x):
        if isinstance(x, str):
            return float(x.replace(",", "."))
        return float(x)
    fa, fb = num(a), num(b)
    if fa == fb:
        return None
    return a if fa > fb else b
''',
    tests=(
        T("int_float", 'assert compare_one(1, 2.5) == 2.5'),
        T("int_str_comma", 'assert compare_one(1, "2,3") == "2,3"'),
        T("str_str", 'assert compare_one("5,1", "6") == "6"'),
        T("equal_str_int", 'assert compare_one("1", 1) is None'),
        T("returns_original_str", 'r = compare_one("7.5", 2)\nassert r == "7.5" and isinstance(r, str)'),
        T("returns_original_int", 'r = compare_one(3, "2,9")\nassert r == 3 and isinstance(r, int)'),
        T("negative_str", 'assert compare_one("-1,5", -2) == "-1,5"'),
        T("equal_float_str", 'assert compare_one(2.5, "2,5") is None'),
        T("first_larger", 'assert compare_one(10, 9.99) == 10'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="he_numerical_letter_grade",
    suite="humaneval",
    title="GPA to letter grade",
    entry_points=("numerical_letter_grade",),
    source_note="Adapted from HumanEval entry point numerical_letter_grade.",
    prompt='''Write a Python function `numerical_letter_grade(grades: list[float]) -> list[str]`
that maps each GPA to a letter grade using this table (thresholds are
strict "greater than" except for the exact values 4.0 and 0.0):

    GPA == 4.0  -> "A+"
    GPA >  3.7  -> "A"
    GPA >  3.3  -> "A-"
    GPA >  3.0  -> "B+"
    GPA >  2.7  -> "B"
    GPA >  2.3  -> "B-"
    GPA >  2.0  -> "C+"
    GPA >  1.7  -> "C"
    GPA >  1.3  -> "C-"
    GPA >  1.0  -> "D+"
    GPA >  0.7  -> "D"
    GPA >  0.0  -> "D-"
    GPA == 0.0  -> "E"

Example:
    numerical_letter_grade([4.0, 3, 1.7, 2, 3.5]) -> ["A+", "B", "C-", "C", "A-"]
''',
    reference='''
def numerical_letter_grade(grades):
    table = [(3.7, "A"), (3.3, "A-"), (3.0, "B+"), (2.7, "B"), (2.3, "B-"), (2.0, "C+"),
             (1.7, "C"), (1.3, "C-"), (1.0, "D+"), (0.7, "D"), (0.0, "D-")]
    out = []
    for g in grades:
        if g == 4.0:
            out.append("A+"); continue
        for th, letter in table:
            if g > th:
                out.append(letter); break
        else:
            out.append("E")
    return out
''',
    tests=(
        T("example", 'assert numerical_letter_grade([4.0, 3, 1.7, 2, 3.5]) == ["A+", "B", "C-", "C", "A-"]'),
        T("top", 'assert numerical_letter_grade([4.0]) == ["A+"]'),
        T("zero", 'assert numerical_letter_grade([0.0]) == ["E"]'),
        T("boundary_3_7", 'assert numerical_letter_grade([3.7]) == ["A-"]'),
        T("just_above_3_7", 'assert numerical_letter_grade([3.71]) == ["A"]'),
        T("boundary_1_0", 'assert numerical_letter_grade([1.0]) == ["D"]'),
        T("tiny_positive", 'assert numerical_letter_grade([0.1]) == ["D-"]'),
        T("boundary_0_7", 'assert numerical_letter_grade([0.7]) == ["D-"]'),
        T("empty", 'assert numerical_letter_grade([]) == []'),
        T("sweep", 'assert numerical_letter_grade([3.9, 3.2, 2.8, 2.4, 2.1, 1.5, 1.2]) == ["A", "B+", "B", "B-", "C+", "C-", "D+"]'),
    ),
))
