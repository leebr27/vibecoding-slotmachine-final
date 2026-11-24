"""Ten practical scripting / data-manipulation tasks in the style of MBPP
(Austin et al., 2021).

`mbpp_remove_occ` and `mbpp_sort_matrix` are adapted directly from MBPP
problems; the other eight follow MBPP's format (short practical function,
one-paragraph description) but tighten the specification so that 8-10
granular tests can pin down behaviour. All test suites are ours.
"""
from .schema import Task, T

TASKS: list[Task] = []

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="mbpp_remove_occ",
    suite="mbpp",
    title="Remove first and last occurrence of a character",
    entry_points=("remove_occ",),
    source_note="Adapted from MBPP (remove_Occ).",
    prompt='''Write a Python function `remove_occ(s: str, ch: str) -> str` that removes
the first and the last occurrence of the single character `ch` from `s`.
If `ch` occurs exactly once, remove that one occurrence. If it does not occur,
return `s` unchanged. Matching is case-sensitive.

Example:
    remove_occ("hello", "l") -> "heo"
''',
    reference='''
def remove_occ(s, ch):
    i = s.find(ch)
    if i == -1:
        return s
    s = s[:i] + s[i + 1:]
    j = s.rfind(ch)
    if j == -1:
        return s
    return s[:j] + s[j + 1:]
''',
    tests=(
        T("hello", 'assert remove_occ("hello", "l") == "heo"'),
        T("ends", 'assert remove_occ("abcda", "a") == "bcd"'),
        T("php", 'assert remove_occ("PHP", "P") == "H"'),
        T("single_occ", 'assert remove_occ("abc", "b") == "ac"'),
        T("absent", 'assert remove_occ("abc", "z") == "abc"'),
        T("empty", 'assert remove_occ("", "a") == ""'),
        T("many", 'assert remove_occ("aaaa", "a") == "aa"'),
        T("only_char", 'assert remove_occ("a", "a") == ""'),
        T("adjacent", 'assert remove_occ("xaay", "a") == "xy"'),
        T("case_sensitive", 'assert remove_occ("Abaa", "A") == "baa"'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="mbpp_sort_matrix",
    suite="mbpp",
    title="Sort matrix rows by row sum",
    entry_points=("sort_matrix",),
    source_note="Adapted from MBPP (sort_matrix).",
    prompt='''Write a Python function `sort_matrix(m: list[list[int]]) -> list[list[int]]`
that returns the rows of `m` sorted in ascending order of their row sums.
Rows with equal sums keep their original relative order. Rows may have
different lengths (an empty row has sum 0). Do not modify the input.

Example:
    sort_matrix([[1, 2, 3], [2, 4, 5], [1, 1, 1]]) -> [[1, 1, 1], [1, 2, 3], [2, 4, 5]]
''',
    reference='''
def sort_matrix(m):
    return [list(r) for r in sorted(m, key=sum)]
''',
    tests=(
        T("example", 'assert sort_matrix([[1, 2, 3], [2, 4, 5], [1, 1, 1]]) == [[1, 1, 1], [1, 2, 3], [2, 4, 5]]'),
        T("empty", 'assert sort_matrix([]) == []'),
        T("stable", 'assert sort_matrix([[3], [1, 2], [2, 1], [0]]) == [[0], [3], [1, 2], [2, 1]]'),
        T("negatives", 'assert sort_matrix([[5, -10], [0], [-1, -1]]) == [[5, -10], [-1, -1], [0]]'),
        T("ragged", 'assert sort_matrix([[1, 1, 1, 1], [5], [2, 2]]) == [[1, 1, 1, 1], [2, 2], [5]]'),
        T("empty_row", 'assert sort_matrix([[1], [], [-1]]) == [[-1], [], [1]]'),
        T("no_mutation", 'm = [[3, 3], [1]]\nsort_matrix(m)\nassert m == [[3, 3], [1]]'),
        T("single", 'assert sort_matrix([[7, 8]]) == [[7, 8]]'),
        T("already_sorted", 'assert sort_matrix([[1], [2], [3]]) == [[1], [2], [3]]'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="mbpp_rle",
    suite="mbpp",
    title="Run-length compression round trip",
    entry_points=("compress", "decompress"),
    source_note="MBPP-style (run-length encoding).",
    prompt='''Write two Python functions.

`compress(s: str) -> str`: `s` contains only ASCII letters. Replace each
maximal run of the same character with the character followed by the run
length, but omit the length when it is 1. Matching is case-sensitive.

`decompress(s: str) -> str`: inverse of compress. Each letter may be followed
by a decimal count (possibly several digits, and possibly an explicit "1");
a letter with no count appears once.

Examples:
    compress("aaabcc")  -> "a3bc2"
    decompress("a3bc2") -> "aaabcc"
''',
    reference='''
import re
def compress(s):
    out = []
    i = 0
    while i < len(s):
        j = i
        while j < len(s) and s[j] == s[i]:
            j += 1
        n = j - i
        out.append(s[i] + (str(n) if n > 1 else ""))
        i = j
    return "".join(out)

def decompress(s):
    return "".join(c * (int(n) if n else 1) for c, n in re.findall(r"([A-Za-z])(\\d*)", s))
''',
    tests=(
        T("compress_basic", 'assert compress("aaabcc") == "a3bc2"'),
        T("compress_empty", 'assert compress("") == ""'),
        T("compress_no_runs", 'assert compress("abc") == "abc"'),
        T("compress_multi_digit", 'assert compress("a" * 12) == "a12"'),
        T("compress_case", 'assert compress("aAAa") == "aA2a"'),
        T("decompress_basic", 'assert decompress("a3bc2") == "aaabcc"'),
        T("decompress_multi_digit", 'assert decompress("b12") == "b" * 12'),
        T("decompress_explicit_one", 'assert decompress("x1y") == "xy"'),
        T("roundtrip", 'for s in ["zzzzzzzzzzzzzzzq", "ab", "QQqq", "m"]:\n    assert decompress(compress(s)) == s'),
        T("decompress_empty", 'assert decompress("") == ""'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="mbpp_top_k_words",
    suite="mbpp",
    title="Top-k word frequencies",
    entry_points=("top_k_words",),
    source_note="MBPP-style (word frequency).",
    prompt='''Write a Python function `top_k_words(text: str, k: int) -> list[tuple[str, int]]`.

A word is a maximal run of ASCII letters (a-z, A-Z); every other character
(digits, apostrophes, punctuation, whitespace) separates words. Words are
compared case-insensitively and reported in lowercase. Return the k most
frequent words as (word, count) tuples, ordered by count descending and then
alphabetically ascending. If there are fewer than k distinct words, return
all of them.

Example:
    top_k_words("the cat and the hat", 2) -> [("the", 2), ("and", 1)]
''',
    reference='''
import re
from collections import Counter
def top_k_words(text, k):
    c = Counter(w.lower() for w in re.findall(r"[A-Za-z]+", text))
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:max(k, 0)]
''',
    tests=(
        T("example", 'assert top_k_words("the cat and the hat", 2) == [("the", 2), ("and", 1)]'),
        T("tie_alpha", 'assert top_k_words("b a c b a c", 3) == [("a", 2), ("b", 2), ("c", 2)]'),
        T("case_insensitive", 'assert top_k_words("Dog dog DOG cat", 1) == [("dog", 3)]'),
        T("apostrophe_splits", 'assert top_k_words("don\'t don\'t stop", 2) == [("don", 2), ("t", 2)]'),
        T("digits_split", 'assert top_k_words("abc123abc x", 1) == [("abc", 2)]'),
        T("empty_text", 'assert top_k_words("", 3) == []'),
        T("k_too_large", 'assert top_k_words("one two", 5) == [("one", 1), ("two", 1)]'),
        T("k_zero", 'assert top_k_words("a b c", 0) == []'),
        T("tuples", 'r = top_k_words("x y", 2)\nassert all(isinstance(t, tuple) for t in r)'),
        T("punctuation", 'assert top_k_words("Hi! hi? HI... ok.", 2) == [("hi", 3), ("ok", 1)]'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="mbpp_normalize_phone",
    suite="mbpp",
    title="Normalize US phone numbers",
    entry_points=("normalize_phone",),
    source_note="MBPP-style (string validation / formatting).",
    prompt='''Write a Python function `normalize_phone(s: str) -> str` for US phone numbers.

Allowed characters are digits, spaces, "-", ".", "(", ")" and a leading "+".
Any other character makes the input invalid. Extract the digits. If there are
11 digits and the first is "1", drop that leading country code. The result
must then be exactly 10 digits, and neither the area code (digit 1) nor the
exchange code (digit 4) may start with 0 or 1. Return the number formatted
as "(XXX) XXX-XXXX". Raise ValueError for any invalid input.

Example:
    normalize_phone("+1 617.495.1000") -> "(617) 495-1000"
''',
    reference='''
def normalize_phone(s):
    s = s.strip()
    body = s[1:] if s.startswith("+") else s
    if any(not (c.isdigit() or c in " -.()") for c in body):
        raise ValueError(s)
    d = [c for c in body if c.isdigit()]
    if len(d) == 11 and d[0] == "1":
        d = d[1:]
    if len(d) != 10 or d[0] in "01" or d[3] in "01":
        raise ValueError(s)
    d = "".join(d)
    return f"({d[:3]}) {d[3:6]}-{d[6:]}"
''',
    tests=(
        T("dashes", 'assert normalize_phone("617-495-1000") == "(617) 495-1000"'),
        T("parens", 'assert normalize_phone("(617) 495 1000") == "(617) 495-1000"'),
        T("dots_plus1", 'assert normalize_phone("+1 617.495.1000") == "(617) 495-1000"'),
        T("leading_1", 'assert normalize_phone("1-617-495-1000") == "(617) 495-1000"'),
        T("bare", 'assert normalize_phone("6174951000") == "(617) 495-1000"'),
        T("too_short", 'try:\n    normalize_phone("495-1000")\n    raise AssertionError("expected ValueError")\nexcept ValueError:\n    pass'),
        T("bad_area_code", 'try:\n    normalize_phone("117 495 1000")\n    raise AssertionError("expected ValueError")\nexcept ValueError:\n    pass'),
        T("bad_exchange", 'try:\n    normalize_phone("617-095-1000")\n    raise AssertionError("expected ValueError")\nexcept ValueError:\n    pass'),
        T("letters", 'try:\n    normalize_phone("617-495-10OO")\n    raise AssertionError("expected ValueError")\nexcept ValueError:\n    pass'),
        T("wrong_country", 'try:\n    normalize_phone("+2 617 495 1000")\n    raise AssertionError("expected ValueError")\nexcept ValueError:\n    pass'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="mbpp_flatten",
    suite="mbpp",
    title="Deep flatten of nested sequences",
    entry_points=("flatten",),
    source_note="MBPP-style (flatten nested list).",
    prompt='''Write a Python function `flatten(nested) -> list`.

Lists and tuples are containers and are flattened recursively, in order.
Everything else (ints, strings, bytes, dicts, None, ...) is an atom and is
kept as-is; in particular strings are NOT split into characters. The input
itself may be a list or a tuple. Your function must handle nesting depth of
at least 5000 without raising RecursionError.

Example:
    flatten([1, [2, (3, [4])], "ab"]) -> [1, 2, 3, 4, "ab"]
''',
    reference='''
def flatten(nested):
    out = []
    stack = [iter(nested)]
    while stack:
        try:
            x = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        if isinstance(x, (list, tuple)):
            stack.append(iter(x))
        else:
            out.append(x)
    return out
''',
    tests=(
        T("example", 'assert flatten([1, [2, (3, [4])], "ab"]) == [1, 2, 3, 4, "ab"]'),
        T("empty", 'assert flatten([]) == []'),
        T("empty_nested", 'assert flatten([[], [[]], ()]) == []'),
        T("strings_atomic", 'assert flatten(("a", ["bc", ("d",)])) == ["a", "bc", "d"]'),
        T("dict_atomic", 'assert flatten([{"k": [1]}, [2]]) == [{"k": [1]}, 2]'),
        T("none_atom", 'assert flatten([None, [None]]) == [None, None]'),
        T("bytes_atom", 'assert flatten([b"xy", [b"z"]]) == [b"xy", b"z"]'),
        T("order", 'assert flatten([[3, [2]], 1, [[0]]]) == [3, 2, 1, 0]'),
        T("deep", 'x = [42]\nfor _ in range(5000):\n    x = [x]\nassert flatten(x) == [42]'),
        T("returns_list", 'assert isinstance(flatten((1, 2)), list)'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="mbpp_roman",
    suite="mbpp",
    title="Strict Roman numeral conversion",
    entry_points=("to_roman", "from_roman"),
    source_note="MBPP-style (Roman numerals), with strict validation.",
    prompt='''Write two Python functions for standard (subtractive) Roman numerals.

`to_roman(n: int) -> str` for 1 <= n <= 3999; raise ValueError otherwise.

`from_roman(s: str) -> int` accepts only canonical uppercase numerals, i.e.
exactly the strings that `to_roman` can produce. Raise ValueError for
anything else, including the empty string, lowercase input, and
non-canonical forms such as "IIII", "IC", "VX" or "MMMM".

Example:
    to_roman(1994) -> "MCMXCIV";  from_roman("MCMXCIV") -> 1994
''',
    reference='''
_VALS = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
         (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
def to_roman(n):
    if not isinstance(n, int) or not 1 <= n <= 3999:
        raise ValueError(n)
    out = []
    for v, r in _VALS:
        while n >= v:
            out.append(r); n -= v
    return "".join(out)

def from_roman(s):
    if not isinstance(s, str) or not s:
        raise ValueError(s)
    total, i = 0, 0
    for v, r in _VALS:
        while s.startswith(r, i):
            total += v; i += len(r)
    if i != len(s) or not 1 <= total <= 3999 or to_roman(total) != s:
        raise ValueError(s)
    return total
''',
    tests=(
        T("to_1994", 'assert to_roman(1994) == "MCMXCIV"'),
        T("to_3999", 'assert to_roman(3999) == "MMMCMXCIX"'),
        T("to_zero", 'try:\n    to_roman(0)\n    raise AssertionError("expected ValueError")\nexcept ValueError:\n    pass'),
        T("to_4000", 'try:\n    to_roman(4000)\n    raise AssertionError("expected ValueError")\nexcept ValueError:\n    pass'),
        T("from_1994", 'assert from_roman("MCMXCIV") == 1994'),
        T("from_iiii", 'try:\n    from_roman("IIII")\n    raise AssertionError("expected ValueError")\nexcept ValueError:\n    pass'),
        T("from_ic", 'try:\n    from_roman("IC")\n    raise AssertionError("expected ValueError")\nexcept ValueError:\n    pass'),
        T("from_lower", 'try:\n    from_roman("xiv")\n    raise AssertionError("expected ValueError")\nexcept ValueError:\n    pass'),
        T("from_empty", 'try:\n    from_roman("")\n    raise AssertionError("expected ValueError")\nexcept ValueError:\n    pass'),
        T("roundtrip_all", 'assert all(from_roman(to_roman(n)) == n for n in range(1, 4000))'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="mbpp_merge_intervals",
    suite="mbpp",
    title="Merge overlapping intervals",
    entry_points=("merge_intervals",),
    source_note="MBPP-style (interval merging).",
    prompt='''Write a Python function `merge_intervals(intervals) -> list[list[int]]`.

`intervals` is a list of closed intervals given as 2-element lists or tuples
[start, end] with start <= end, in any order. Merge all intervals that overlap
or touch (so [1, 2] and [2, 3] merge into [1, 3]). Return a new list of
2-element lists sorted by start. Do not modify the input.

Example:
    merge_intervals([[8, 10], [1, 3], [2, 6]]) -> [[1, 6], [8, 10]]
''',
    reference='''
def merge_intervals(intervals):
    out = []
    for s, e in sorted((list(x) for x in intervals), key=lambda x: x[0]):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out
''',
    tests=(
        T("example", 'assert merge_intervals([[8, 10], [1, 3], [2, 6]]) == [[1, 6], [8, 10]]'),
        T("classic", 'assert merge_intervals([[1, 3], [2, 6], [8, 10], [15, 18]]) == [[1, 6], [8, 10], [15, 18]]'),
        T("touching", 'assert merge_intervals([[1, 2], [2, 3]]) == [[1, 3]]'),
        T("contained", 'assert merge_intervals([[1, 10], [2, 3], [4, 5]]) == [[1, 10]]'),
        T("empty", 'assert merge_intervals([]) == []'),
        T("tuples_in_lists_out", 'assert merge_intervals([(5, 6), (1, 2)]) == [[1, 2], [5, 6]]'),
        T("no_mutation", 'x = [[1, 4], [2, 5]]\nmerge_intervals(x)\nassert x == [[1, 4], [2, 5]]'),
        T("negatives", 'assert merge_intervals([[-5, -1], [-2, 0], [3, 3]]) == [[-5, 0], [3, 3]]'),
        T("point_intervals", 'assert merge_intervals([[2, 2], [2, 2], [1, 1]]) == [[1, 1], [2, 2]]'),
        T("chain", 'assert merge_intervals([[4, 5], [3, 4], [2, 3], [1, 2]]) == [[1, 5]]'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="mbpp_parse_kv",
    suite="mbpp",
    title="Parse a key=value config line",
    entry_points=("parse_kv",),
    source_note="MBPP-style (string parsing).",
    prompt=r'''Write a Python function `parse_kv(line: str) -> dict`.

`line` is a sequence of items separated by ";". Each item is either
`key=value` or a bare `key` (which maps to True). Split an item on its FIRST
"=" only. Strip whitespace around keys and around unquoted values. A value
may be enclosed in double quotes: inside quotes, ";" is literal, `\"` stands
for a double quote and `\\` for a backslash, and whitespace is preserved; the
surrounding quotes are not part of the value. Empty items (e.g. from a
trailing ";") are ignored. If a key repeats, the later value wins. Values are
always strings (or True for bare keys). Raise ValueError on an unterminated
quoted value.

Example:
    parse_kv('a=1; debug; msg="hi; there"') -> {"a": "1", "debug": True, "msg": "hi; there"}
''',
    reference=r'''
def parse_kv(line):
    items, buf, i, inq = [], [], 0, False
    while i < len(line):
        c = line[i]
        if inq:
            if c == "\\" and i + 1 < len(line):
                buf.append(c); buf.append(line[i + 1]); i += 2; continue
            if c == '"':
                inq = False
            buf.append(c)
        else:
            if c == '"':
                inq = True; buf.append(c)
            elif c == ";":
                items.append("".join(buf)); buf = []
            else:
                buf.append(c)
        i += 1
    if inq:
        raise ValueError("unterminated quote")
    items.append("".join(buf))
    out = {}
    for item in items:
        if not item.strip():
            continue
        if "=" not in item:
            out[item.strip()] = True
            continue
        k, v = item.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            body, res, j = v[1:-1], [], 0
            while j < len(body):
                if body[j] == "\\" and j + 1 < len(body):
                    res.append(body[j + 1]); j += 2
                else:
                    res.append(body[j]); j += 1
            v = "".join(res)
        out[k] = v
    return out
''',
    tests=(
        T("basic", 'assert parse_kv("a=1; b=2") == {"a": "1", "b": "2"}'),
        T("bare_key", 'assert parse_kv("debug; level=3") == {"debug": True, "level": "3"}'),
        T("quoted_semicolon", 'assert parse_kv(\'msg="hi; there"\') == {"msg": "hi; there"}'),
        T("escaped_quote", r'''assert parse_kv('q="say \\"x\\""') == {"q": 'say "x"'}'''),
        T("trailing_empty", 'assert parse_kv("a=1;;") == {"a": "1"}'),
        T("duplicate_override", 'assert parse_kv("a=1; a=2") == {"a": "2"}'),
        T("whitespace", 'assert parse_kv("  k =  v  ") == {"k": "v"}'),
        T("first_equals", 'assert parse_kv("url=a=b") == {"url": "a=b"}'),
        T("quoted_whitespace", 'assert parse_kv(\'s = "  x "\') == {"s": "  x "}'),
        T("unterminated", 'try:\n    parse_kv(\'a="oops\')\n    raise AssertionError("expected ValueError")\nexcept ValueError:\n    pass'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="mbpp_column_stats",
    suite="mbpp",
    title="Summary statistics for a CSV column",
    entry_points=("column_stats",),
    source_note="MBPP-style (CSV processing).",
    prompt='''Write a Python function `column_stats(csv_text: str, column: str) -> dict`.

`csv_text` is comma-separated text whose first non-blank line is a header.
Fields may be double-quoted (quoted fields can contain commas). Blank lines
are skipped. For the named column, strip whitespace from each cell, ignore
empty cells, and parse the rest as floats. Return a dict with keys
"count", "sum", "mean", "min", "max". If there are no values, return
count 0, sum 0.0 and None for mean, min and max. Raise KeyError if the
column does not exist and ValueError if a non-empty cell is not numeric.

Example:
    column_stats("name,score\\nann,3\\nbob,5\\n", "score")
      -> {"count": 2, "sum": 8.0, "mean": 4.0, "min": 3.0, "max": 5.0}
''',
    reference='''
import csv, io
def column_stats(csv_text, column):
    rows = [r for r in csv.reader(io.StringIO(csv_text)) if any(c.strip() for c in r)]
    if not rows:
        raise KeyError(column)
    header = [h.strip() for h in rows[0]]
    if column not in header:
        raise KeyError(column)
    idx = header.index(column)
    vals = []
    for r in rows[1:]:
        cell = r[idx].strip() if idx < len(r) else ""
        if cell == "":
            continue
        vals.append(float(cell))
    if not vals:
        return {"count": 0, "sum": 0.0, "mean": None, "min": None, "max": None}
    return {"count": len(vals), "sum": float(sum(vals)), "mean": sum(vals) / len(vals),
            "min": min(vals), "max": max(vals)}
''',
    tests=(
        T("example", 'assert column_stats("name,score\\nann,3\\nbob,5\\n", "score") == {"count": 2, "sum": 8.0, "mean": 4.0, "min": 3.0, "max": 5.0}'),
        T("quoted_commas", 'r = column_stats(\'name,score\\n"Doe, Jane",10\\n"Roe, R",20\\n\', "score")\nassert r["sum"] == 30.0 and r["count"] == 2'),
        T("blank_lines", 'r = column_stats("a,b\\n\\n1,2\\n\\n3,4\\n", "b")\nassert r["count"] == 2 and r["max"] == 4.0'),
        T("empty_cells", 'r = column_stats("a,b\\n1,\\n2, \\n3,9\\n", "b")\nassert r == {"count": 1, "sum": 9.0, "mean": 9.0, "min": 9.0, "max": 9.0}'),
        T("no_values", 'assert column_stats("a,b\\n1,\\n", "b") == {"count": 0, "sum": 0.0, "mean": None, "min": None, "max": None}'),
        T("missing_column", 'try:\n    column_stats("a,b\\n1,2\\n", "c")\n    raise AssertionError("expected KeyError")\nexcept KeyError:\n    pass'),
        T("non_numeric", 'try:\n    column_stats("a,b\\n1,x\\n", "b")\n    raise AssertionError("expected ValueError")\nexcept ValueError:\n    pass'),
        T("whitespace_cells", 'r = column_stats("a,b\\n1,  2.5 \\n", "b")\nassert r["min"] == 2.5'),
        T("negatives_floats", 'r = column_stats("x\\n-1.5\\n2\\n", "x")\nassert r["min"] == -1.5 and r["mean"] == 0.25'),
        T("leading_blank_header", 'r = column_stats("\\n\\nx,y\\n1,2\\n", "y")\nassert r["count"] == 1'),
    ),
))
