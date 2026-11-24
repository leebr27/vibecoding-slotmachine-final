"""Ten original multi-function / stateful tasks.

These are written for this project. Each specification enumerates several
interacting rules; each test pins down one rule. A solution that gets the
"main idea" right but drops one rule passes 8 or 9 of 10 tests, so these
tasks are where near-misses arise naturally. Every rule a test checks is
stated explicitly in the prompt.
"""
from .schema import Task, T

TASKS: list[Task] = []


def _raises(call: str, exc: str) -> str:
    return (f"try:\n    {call}\n    raise AssertionError('expected {exc}')\n"
            f"except {exc}:\n    pass")


# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="orig_ttl_cache",
    suite="original",
    title="LRU cache with time-to-live",
    entry_points=("TTLCache",),
    prompt='''Implement a Python class `TTLCache` (an LRU cache whose entries expire).
Time is passed in explicitly as `now` (a float), never read from a clock.

    TTLCache(capacity: int, ttl: float)      # capacity >= 1
    put(key, value, now: float) -> None
    get(key, now: float) -> value or None
    size(now: float) -> int

Rules:
1. An entry written by `put` at time t expires at t + ttl. It is expired at
   time `now` when now >= t + ttl.
2. `get` returns the value of an unexpired entry and makes it the most
   recently used. `get` does NOT extend the entry's expiry time.
3. `get` on a missing or expired key returns None (an expired entry is removed).
4. `put` on an existing key overwrites the value, resets its expiry to
   now + ttl, and makes it most recently used. Overwriting never evicts.
5. When `put` inserts a NEW key and the cache holds `capacity` entries, first
   remove every expired entry; if the cache is still full, evict the least
   recently used entry.
6. `size(now)` returns the number of unexpired entries at time `now`.
''',
    reference='''
from collections import OrderedDict
class TTLCache:
    def __init__(self, capacity, ttl):
        self.capacity, self.ttl = capacity, ttl
        self.d = OrderedDict()  # key -> (value, expires_at)
    def _expired(self, key, now):
        return now >= self.d[key][1]
    def get(self, key, now):
        if key not in self.d:
            return None
        if self._expired(key, now):
            del self.d[key]
            return None
        self.d.move_to_end(key)
        return self.d[key][0]
    def put(self, key, value, now):
        if key in self.d:
            self.d[key] = (value, now + self.ttl)
            self.d.move_to_end(key)
            return
        if len(self.d) >= self.capacity:
            for k in [k for k in self.d if self._expired(k, now)]:
                del self.d[k]
            if len(self.d) >= self.capacity:
                self.d.popitem(last=False)
        self.d[key] = (value, now + self.ttl)
    def size(self, now):
        return sum(1 for k in self.d if not self._expired(k, now))
''',
    tests=(
        T("basic", 'c = TTLCache(2, 10)\nc.put("a", 1, 0)\nassert c.get("a", 1) == 1'),
        T("missing", 'c = TTLCache(2, 10)\nassert c.get("zz", 0) is None'),
        T("expiry_boundary", 'c = TTLCache(2, 10)\nc.put("a", 1, 0)\nassert c.get("a", 9.999) == 1\nassert c.get("a", 10) is None'),
        T("get_no_refresh", 'c = TTLCache(2, 10)\nc.put("a", 1, 0)\nc.get("a", 5)\nassert c.get("a", 10) is None'),
        T("put_refreshes", 'c = TTLCache(2, 10)\nc.put("a", 1, 0)\nc.put("a", 2, 5)\nassert c.get("a", 12) == 2'),
        T("lru_eviction", 'c = TTLCache(2, 100)\nc.put("a", 1, 0)\nc.put("b", 2, 1)\nc.get("a", 2)\nc.put("c", 3, 3)\nassert c.get("b", 4) is None and c.get("a", 4) == 1 and c.get("c", 4) == 3'),
        T("purge_before_evict", 'c = TTLCache(2, 10)\nc.put("a", 1, 0)\nc.put("b", 2, 5)\nc.put("c", 3, 11)\nassert c.get("b", 11) == 2 and c.get("c", 11) == 3'),
        T("overwrite_no_evict", 'c = TTLCache(2, 100)\nc.put("a", 1, 0)\nc.put("b", 2, 1)\nc.put("a", 9, 2)\nassert c.get("b", 3) == 2 and c.get("a", 3) == 9'),
        T("overwrite_updates_recency", 'c = TTLCache(2, 100)\nc.put("a", 1, 0)\nc.put("b", 2, 1)\nc.put("a", 3, 2)\nc.put("c", 4, 3)\nassert c.get("b", 4) is None and c.get("a", 4) == 3'),
        T("size_unexpired", 'c = TTLCache(3, 10)\nc.put("a", 1, 0)\nc.put("b", 2, 5)\nassert c.size(4) == 2 and c.size(12) == 1 and c.size(20) == 0'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="orig_mini_interpreter",
    suite="original",
    title="Integer expression interpreter",
    entry_points=("evaluate",),
    prompt='''Write a Python function `evaluate(expr: str) -> int` that evaluates an
integer arithmetic expression WITHOUT using eval() or exec().

Grammar and semantics:
- Tokens: non-negative integer literals, + - * / % ^ ( ). Whitespace is ignored.
- Precedence from highest to lowest:
    1. ^ (exponentiation, RIGHT-associative; the exponent may itself carry a
       unary minus, e.g. 2^-1)
    2. unary - (so -2^2 == -4, and --3 == 3)
    3. * / % (left-associative)
    4. + - (left-associative)
- "/" is integer division that truncates toward zero (7 / -2 == -3), unlike
  Python's //. "%" is the matching remainder, with the sign of the dividend,
  so that (a / b) * b + a % b == a (e.g. -7 % 3 == -1).
- Division or remainder by zero raises ZeroDivisionError.
- A negative exponent raises ValueError.
- Any malformed input raises SyntaxError.
''',
    reference='''
import re
def evaluate(expr):
    toks = re.findall(r"\\d+|[-+*/%^()]|\\S", expr)
    pos = [0]
    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None
    def take():
        t = peek()
        if t is None:
            raise SyntaxError("unexpected end")
        pos[0] += 1
        return t
    def tdiv(a, b):
        if b == 0:
            raise ZeroDivisionError
        q = abs(a) // abs(b)
        return q if (a >= 0) == (b >= 0) else -q
    def expr_():
        v = term()
        while peek() in ("+", "-"):
            op = take(); r = term()
            v = v + r if op == "+" else v - r
        return v
    def term():
        v = unary()
        while peek() in ("*", "/", "%"):
            op = take(); r = unary()
            if op == "*":
                v = v * r
            elif op == "/":
                v = tdiv(v, r)
            else:
                v = v - tdiv(v, r) * r
        return v
    def unary():
        if peek() == "-":
            take()
            return -unary()
        return power()
    def power():
        base = atom()
        if peek() == "^":
            take()
            e = unary()
            if e < 0:
                raise ValueError("negative exponent")
            return base ** e
        return base
    def atom():
        t = take()
        if t.isdigit():
            return int(t)
        if t == "(":
            v = expr_()
            if take() != ")":
                raise SyntaxError("expected )")
            return v
        raise SyntaxError(f"unexpected {t!r}")
    v = expr_()
    if peek() is not None:
        raise SyntaxError("trailing input")
    return v
''',
    tests=(
        T("precedence", 'assert evaluate("1 + 2 * 3") == 7'),
        T("parens", 'assert evaluate("(1 + 2) * 3") == 9'),
        T("pow_right_assoc", 'assert evaluate("2 ^ 3 ^ 2") == 512'),
        T("unary_vs_pow", 'assert evaluate("-2 ^ 2") == -4'),
        T("trunc_division", 'assert evaluate("7 / -2") == -3 and evaluate("-7 / 2") == -3'),
        T("c_remainder", 'assert evaluate("-7 % 3") == -1 and evaluate("7 % -3") == 1'),
        T("left_assoc", 'assert evaluate("10 - 4 - 3") == 3 and evaluate("100 / 10 / 5") == 2'),
        T("double_unary", 'assert evaluate("2 * --3") == 6'),
        T("errors_zero_and_negexp", _raises('evaluate("1 / (2 - 2)")', "ZeroDivisionError") + "\n" + _raises('evaluate("2 ^ -1")', "ValueError")),
        T("syntax_errors", "\n".join(_raises(f'evaluate("{e}")', "SyntaxError") for e in ["2 +", "(1", "1 2", "3 $ 4"])),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="orig_vending_machine",
    suite="original",
    title="Vending machine with limited change",
    entry_points=("VendingMachine",),
    prompt='''Implement a Python class `VendingMachine`.

    VendingMachine(prices: dict[str, int], coins: dict[int, int])
        prices: item name -> price in cents (multiples of 5)
        coins:  initial coin inventory available for change, denomination -> count
    insert(coin: int) -> bool
    balance() -> int
    select(item: str) -> list[int] | str
    cancel() -> list[int]

Rules:
1. Only 5, 10 and 25 cent coins are accepted. `insert` returns True and adds
   the coin to the balance AND to the machine's coin inventory; any other
   coin is rejected (return False, nothing changes).
2. `select` on an unknown item returns "UNKNOWN". If the balance is below the
   price it returns "INSUFFICIENT". In both cases nothing else changes.
3. Otherwise the change owed is balance - price. Pay it from the current coin
   inventory (which includes coins inserted in this transaction) using the
   FEWEST coins possible. Note that greedy (largest coin first) does not
   always succeed when the inventory is limited; you must find a combination
   whenever one exists.
4. If the exact change cannot be made, return "NO_CHANGE" and change nothing
   (the balance remains).
5. On success, remove the change coins from the inventory, reset the balance
   to 0, and return the change coins as a list sorted in descending order
   ([] when no change is owed).
6. `cancel` returns exactly the coins inserted since the last successful
   `select` or `cancel` (sorted descending), removes them from the inventory,
   and resets the balance to 0.
''',
    reference='''
class VendingMachine:
    def __init__(self, prices, coins):
        self.prices = dict(prices)
        self.inv = {5: 0, 10: 0, 25: 0}
        for c, n in coins.items():
            self.inv[c] = self.inv.get(c, 0) + n
        self.bal = 0
        self.inserted = []
    def insert(self, coin):
        if coin not in (5, 10, 25):
            return False
        self.bal += coin
        self.inv[coin] += 1
        self.inserted.append(coin)
        return True
    def balance(self):
        return self.bal
    def _change(self, amount):
        best = None
        for q in range(min(self.inv[25], amount // 25) + 1):
            r1 = amount - 25 * q
            for d in range(min(self.inv[10], r1 // 10) + 1):
                r2 = r1 - 10 * d
                if r2 % 5 == 0 and r2 // 5 <= self.inv[5]:
                    n = q + d + r2 // 5
                    if best is None or n < best[0]:
                        best = (n, q, d, r2 // 5)
        return best
    def select(self, item):
        if item not in self.prices:
            return "UNKNOWN"
        price = self.prices[item]
        if self.bal < price:
            return "INSUFFICIENT"
        best = self._change(self.bal - price)
        if best is None:
            return "NO_CHANGE"
        _, q, d, f = best
        self.inv[25] -= q; self.inv[10] -= d; self.inv[5] -= f
        self.bal = 0
        self.inserted = []
        return [25] * q + [10] * d + [5] * f
    def cancel(self):
        out = sorted(self.inserted, reverse=True)
        for c in out:
            self.inv[c] -= 1
        self.inserted = []
        self.bal = 0
        return out
''',
    tests=(
        T("insert_balance", 'v = VendingMachine({"gum": 15}, {})\nassert v.insert(25) and v.insert(10) and v.balance() == 35'),
        T("reject_coin", 'v = VendingMachine({"gum": 15}, {})\nassert v.insert(1) is False and v.insert(50) is False and v.balance() == 0'),
        T("unknown", 'v = VendingMachine({"gum": 15}, {})\nv.insert(25)\nassert v.select("soda") == "UNKNOWN" and v.balance() == 25'),
        T("insufficient", 'v = VendingMachine({"gum": 35}, {})\nv.insert(25)\nassert v.select("gum") == "INSUFFICIENT" and v.balance() == 25'),
        T("exact", 'v = VendingMachine({"gum": 35}, {})\nv.insert(25); v.insert(10)\nassert v.select("gum") == [] and v.balance() == 0'),
        T("fewest_coins", 'v = VendingMachine({"gum": 5}, {25: 2, 10: 5, 5: 5})\nv.insert(25); v.insert(25)\nassert v.select("gum") == [25, 10, 10]'),
        T("non_greedy", 'v = VendingMachine({"gum": 20}, {25: 1, 10: 3})\nv.insert(25); v.insert(25)\nassert v.select("gum") == [10, 10, 10]'),
        T("no_change", 'v = VendingMachine({"gum": 20}, {10: 4})\nv.insert(25)\nassert v.select("gum") == "NO_CHANGE" and v.balance() == 25'),
        T("inserted_coins_as_change", 'v = VendingMachine({"gum": 25}, {})\nv.insert(5); v.insert(25)\nassert v.select("gum") == [5]'),
        T("cancel_exact_coins", 'v = VendingMachine({"gum": 100}, {5: 10})\nv.insert(25); v.insert(10); v.insert(10)\nassert v.cancel() == [25, 10, 10] and v.balance() == 0'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="orig_parser_combinators",
    suite="original",
    title="Parser combinator library",
    entry_points=("char", "string", "satisfy", "seq", "alt", "many", "sep_by", "map_", "parse", "ParseError"),
    prompt='''Write a small parser-combinator library in Python.

A parser is a function `p(s: str, i: int)` that returns `(value, j)` on
success, where j is the index just after the consumed input, or `None` on
failure. Implement:

- `char(c)`: matches the single character c; value is c.
- `string(lit)`: matches the literal string lit; value is lit.
- `satisfy(pred)`: matches one character ch with pred(ch) true; value is ch.
- `seq(*ps)`: runs the parsers in order; value is the list of their values;
  fails if any of them fails.
- `alt(*ps)`: returns the result of the FIRST parser (in argument order) that
  succeeds at position i; fails if none does.
- `many(p)`: zero or more repetitions of p; value is the list of values. It
  stops when p fails OR when p succeeds without consuming input (that last
  non-consuming result is discarded), so it always terminates.
- `sep_by(p, sep)`: zero or more p separated by sep; value is the list of p
  values (separator values dropped). A trailing separator that is not
  followed by a p is NOT consumed.
- `map_(p, f)`: like p but with value f(value).
- `class ParseError(Exception)` with an attribute `pos`.
- `parse(p, s)`: runs p on s at index 0. Returns the value if p succeeds and
  consumes all of s. If p fails, raise ParseError with pos = 0. If p succeeds
  but stops at j < len(s), raise ParseError with pos = j.
''',
    reference='''
class ParseError(Exception):
    def __init__(self, pos, msg=""):
        super().__init__(f"{msg} at {pos}")
        self.pos = pos

def char(c):
    def p(s, i):
        return (c, i + 1) if i < len(s) and s[i] == c else None
    return p

def string(lit):
    def p(s, i):
        return (lit, i + len(lit)) if s.startswith(lit, i) else None
    return p

def satisfy(pred):
    def p(s, i):
        return (s[i], i + 1) if i < len(s) and pred(s[i]) else None
    return p

def seq(*ps):
    def p(s, i):
        vals = []
        for q in ps:
            r = q(s, i)
            if r is None:
                return None
            v, i = r
            vals.append(v)
        return vals, i
    return p

def alt(*ps):
    def p(s, i):
        for q in ps:
            r = q(s, i)
            if r is not None:
                return r
        return None
    return p

def many(q):
    def p(s, i):
        vals = []
        while True:
            r = q(s, i)
            if r is None or r[1] == i:
                return vals, i
            v, i = r
            vals.append(v)
    return p

def sep_by(q, sep):
    def p(s, i):
        r = q(s, i)
        if r is None:
            return [], i
        v, i = r
        vals = [v]
        while True:
            rs = sep(s, i)
            if rs is None:
                return vals, i
            r = q(s, rs[1])
            if r is None:
                return vals, i
            v, i = r
            vals.append(v)
    return p

def map_(q, f):
    def p(s, i):
        r = q(s, i)
        return None if r is None else (f(r[0]), r[1])
    return p

def parse(q, s):
    r = q(s, 0)
    if r is None:
        raise ParseError(0, "no parse")
    if r[1] != len(s):
        raise ParseError(r[1], "unconsumed input")
    return r[0]
''',
    tests=(
        T("char", 'assert char("a")("abc", 0) == ("a", 1) and char("a")("abc", 1) is None'),
        T("string_satisfy", 'assert string("ab")("xab", 1) == ("ab", 3) and satisfy(str.isdigit)("7", 0) == ("7", 1) and satisfy(str.isdigit)("", 0) is None'),
        T("seq", 'assert seq(char("a"), char("b"))("abc", 0) == (["a", "b"], 2) and seq(char("a"), char("c"))("abc", 0) is None'),
        T("alt_order", 'assert alt(string("ab"), string("a"))("ab", 0) == ("ab", 2) and alt(string("a"), string("ab"))("ab", 0) == ("a", 1)'),
        T("many_zero", 'assert many(char("x"))("yyy", 1) == ([], 1)'),
        T("many_nonconsuming", 'p = many(many(char("x")))\nassert p("y", 0) == ([], 0) and p("xx", 0) == ([["x", "x"]], 2)'),
        T("map", 'digit = map_(satisfy(str.isdigit), int)\nassert map_(many(digit), sum)("123", 0) == (6, 3)'),
        T("sep_by_trailing", 'd = satisfy(str.isdigit)\nassert sep_by(d, char(","))("1,2,", 0) == (["1", "2"], 3) and sep_by(d, char(","))("", 0) == ([], 0)'),
        T("parse_errors", 'p = char("a")\nassert parse(p, "a") == "a"\ntry:\n    parse(p, "b"); raise AssertionError("no error")\nexcept ParseError as e:\n    assert e.pos == 0\ntry:\n    parse(many(p), "aab"); raise AssertionError("no error")\nexcept ParseError as e:\n    assert e.pos == 2'),
        T("integration_list", 'num = map_(seq(satisfy(str.isdigit), many(satisfy(str.isdigit))), lambda v: int(v[0] + "".join(v[1])))\nlst = map_(seq(char("["), sep_by(num, char(",")), char("]")), lambda v: v[1])\nassert parse(lst, "[1,22,333]") == [1, 22, 333] and parse(lst, "[]") == []'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="orig_interval_scheduler",
    suite="original",
    title="Room booking scheduler",
    entry_points=("Scheduler",),
    prompt='''Implement a Python class `Scheduler` for booking a single room.
All bookings are half-open integer intervals [start, end).

    book(start: int, end: int) -> bool
    cancel(start: int, end: int) -> bool
    bookings() -> list[tuple[int, int]]
    free_slots(lo: int, hi: int, min_len: int = 1) -> list[tuple[int, int]]

Rules:
1. `book` raises ValueError if start >= end. It returns False (and changes
   nothing) if the interval overlaps any existing booking; otherwise it records
   the booking and returns True. Intervals that merely touch, like [0, 5) and
   [5, 10), do not overlap.
2. `cancel` removes the booking with exactly this start and end and returns
   True; if no booking matches exactly, it returns False.
3. `bookings` returns all bookings as (start, end) tuples sorted by start.
4. `free_slots` returns the maximal free intervals inside the window [lo, hi)
   as (start, end) tuples sorted by start, keeping only those with
   end - start >= min_len. Bookings that extend outside the window are
   clipped to it.
''',
    reference='''
import bisect
class Scheduler:
    def __init__(self):
        self.b = []
    def book(self, start, end):
        if start >= end:
            raise ValueError("empty interval")
        for s, e in self.b:
            if start < e and s < end:
                return False
        bisect.insort(self.b, (start, end))
        return True
    def cancel(self, start, end):
        if (start, end) in self.b:
            self.b.remove((start, end))
            return True
        return False
    def bookings(self):
        return list(self.b)
    def free_slots(self, lo, hi, min_len=1):
        out, cur = [], lo
        for s, e in self.b:
            if e <= lo or s >= hi:
                continue
            s, e = max(s, lo), min(e, hi)
            if s > cur:
                out.append((cur, s))
            cur = max(cur, e)
        if cur < hi:
            out.append((cur, hi))
        return [(a, b) for a, b in out if b - a >= min_len]
''',
    tests=(
        T("book_ok", 's = Scheduler()\nassert s.book(9, 10) is True and s.bookings() == [(9, 10)]'),
        T("overlap_rejected", 's = Scheduler()\ns.book(9, 12)\nassert s.book(11, 13) is False and s.book(8, 10) is False and s.book(10, 11) is False and s.bookings() == [(9, 12)]'),
        T("touching_allowed", 's = Scheduler()\nassert s.book(0, 5) and s.book(5, 10) and s.book(-3, 0)'),
        T("invalid_interval", _raises("Scheduler().book(5, 5)", "ValueError")),
        T("cancel_and_rebook", 's = Scheduler()\ns.book(1, 4)\nassert s.cancel(1, 4) is True and s.book(2, 3) is True'),
        T("cancel_inexact", 's = Scheduler()\ns.book(1, 4)\nassert s.cancel(1, 3) is False and s.cancel(7, 8) is False and s.bookings() == [(1, 4)]'),
        T("bookings_sorted", 's = Scheduler()\ns.book(20, 30); s.book(0, 5); s.book(10, 12)\nassert s.bookings() == [(0, 5), (10, 12), (20, 30)]'),
        T("free_basic", 's = Scheduler()\ns.book(2, 4); s.book(6, 7)\nassert s.free_slots(0, 10) == [(0, 2), (4, 6), (7, 10)]'),
        T("free_clipped", 's = Scheduler()\ns.book(-5, 3); s.book(8, 20)\nassert s.free_slots(0, 10) == [(3, 8)] and Scheduler().free_slots(0, 4) == [(0, 4)]'),
        T("free_min_len", 's = Scheduler()\ns.book(2, 4); s.book(5, 9)\nassert s.free_slots(0, 12, min_len=2) == [(0, 2), (9, 12)]'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="orig_graph_coloring",
    suite="original",
    title="Graph k-coloring constraint solver",
    entry_points=("color_graph",),
    prompt='''Write a Python function
`color_graph(nodes, edges, k, precolored=None) -> dict | None`.

- `nodes` is an iterable of hashable node names. `edges` is a list of
  (u, v) pairs describing an undirected graph; any endpoint not listed in
  `nodes` is also a node.
- Colors are the integers 0 .. k-1.
- `precolored` (optional) maps some nodes to fixed colors that must be kept.
- Return a dict mapping EVERY node to a color such that the two endpoints of
  every edge get different colors and all precolored nodes keep their color.
- Return None if no such coloring exists. This includes graphs with a
  self-loop (u, u), precolorings that conflict, and k too small.
- A greedy one-pass coloring is not sufficient: if a valid coloring exists
  you must find one (backtracking search is fine; graphs have <= 30 nodes).
''',
    reference='''
def color_graph(nodes, edges, k, precolored=None):
    precolored = dict(precolored or {})
    allnodes = list(dict.fromkeys(list(nodes) + [x for e in edges for x in e] + list(precolored)))
    adj = {n: set() for n in allnodes}
    for u, v in edges:
        if u == v:
            return None
        adj[u].add(v); adj[v].add(u)
    for n, c in precolored.items():
        if not (0 <= c < k):
            return None
    col = dict(precolored)
    for u, v in edges:
        if u in col and v in col and col[u] == col[v]:
            return None
    order = sorted([n for n in allnodes if n not in col], key=lambda n: -len(adj[n]))
    def bt(i):
        if i == len(order):
            return True
        n = order[i]
        used = {col[m] for m in adj[n] if m in col}
        for c in range(k):
            if c not in used:
                col[n] = c
                if bt(i + 1):
                    return True
                del col[n]
        return False
    return col if bt(0) else None
''',
    test_prelude='''
def _chk_valid(col, nodes, edges, k, pre=None):
    allnodes = set(nodes) | {x for e in edges for x in e}
    assert isinstance(col, dict), f"expected dict, got {col!r}"
    assert set(col) >= allnodes, f"missing nodes {allnodes - set(col)}"
    assert all(0 <= col[n] < k for n in allnodes), "color out of range"
    assert all(col[u] != col[v] for u, v in edges), "adjacent nodes share a color"
    for n, c in (pre or {}).items():
        assert col[n] == c, "precolor not kept"
    return True
''',
    tests=(
        T("triangle_k3", 'e = [(1, 2), (2, 3), (1, 3)]\nassert _chk_valid(color_graph([1, 2, 3], e, 3), [1, 2, 3], e, 3)'),
        T("triangle_k2", 'assert color_graph([1, 2, 3], [(1, 2), (2, 3), (1, 3)], 2) is None'),
        T("isolated_nodes", 'col = color_graph(["a", "b", "z"], [("a", "b")], 2)\nassert _chk_valid(col, ["a", "b", "z"], [("a", "b")], 2) and "z" in col'),
        T("precolored_kept", 'e = [("a", "b"), ("b", "c")]\ncol = color_graph(["a", "b", "c"], e, 2, {"b": 1})\nassert _chk_valid(col, ["a", "b", "c"], e, 2, {"b": 1})'),
        T("precolored_conflict", 'assert color_graph(["a", "b"], [("a", "b")], 3, {"a": 0, "b": 0}) is None'),
        T("self_loop", 'assert color_graph(["a"], [("a", "a")], 5) is None'),
        T("even_cycle_k2", 'e = [(i, (i + 1) % 6) for i in range(6)]\nassert _chk_valid(color_graph(range(6), e, 2), range(6), e, 2)'),
        T("odd_cycle_k2", 'assert color_graph(range(5), [(i, (i + 1) % 5) for i in range(5)], 2) is None'),
        T("implicit_nodes", 'col = color_graph([], [("p", "q"), ("q", "r")], 2)\nassert _chk_valid(col, [], [("p", "q"), ("q", "r")], 2)'),
        T("crown_graph_needs_search", 'n = 5\nnodes = [x for i in range(n) for x in (f"u{i}", f"v{i}")]\ne = [(f"u{i}", f"v{j}") for i in range(n) for j in range(n) if i != j]\nassert _chk_valid(color_graph(nodes, e, 2), nodes, e, 2)'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="orig_wrap_text",
    suite="original",
    title="Paragraph-aware greedy word wrap",
    entry_points=("wrap_text",),
    prompt='''Write a Python function `wrap_text(text: str, width: int) -> str`.

Rules:
1. Raise ValueError if width < 1.
2. Paragraphs are separated by one or more blank lines (a blank line is empty
   or contains only whitespace). Within a paragraph, words are separated by
   any run of whitespace, including single newlines.
3. Wrap each paragraph greedily: place as many words on a line as fit within
   `width` characters, joining words with single spaces. Lines never have
   leading or trailing spaces.
4. A word longer than `width` is split into pieces of exactly `width`
   characters (the last piece may be shorter), and the pieces are then
   treated as separate words.
5. Join lines with "\\n" and separate paragraphs with exactly one empty line.
   Leading and trailing blank lines are dropped; whitespace-only input
   returns "".

Example:
    wrap_text("The quick brown fox jumps over the lazy dog", 10)
      -> "The quick\\nbrown fox\\njumps over\\nthe lazy\\ndog"
''',
    reference='''
import re
def wrap_text(text, width):
    if width < 1:
        raise ValueError("width")
    paras = [p for p in re.split(r"\\n[ \\t\\r\\f\\v]*\\n(?:[ \\t\\r\\f\\v]*\\n)*", text.strip("\\n")) ]
    out = []
    for p in paras:
        words = []
        for w in p.split():
            while len(w) > width:
                words.append(w[:width]); w = w[width:]
            if w:
                words.append(w)
        if not words:
            continue
        lines, cur = [], ""
        for w in words:
            if not cur:
                cur = w
            elif len(cur) + 1 + len(w) <= width:
                cur += " " + w
            else:
                lines.append(cur); cur = w
        lines.append(cur)
        out.append("\\n".join(lines))
    return "\\n\\n".join(out)
''',
    tests=(
        T("example", 'assert wrap_text("The quick brown fox jumps over the lazy dog", 10) == "The quick\\nbrown fox\\njumps over\\nthe lazy\\ndog"'),
        T("exact_fit", 'assert wrap_text("aaa bbb ccc", 7) == "aaa bbb\\nccc"'),
        T("collapse_whitespace", 'assert wrap_text("a   b\\tc", 80) == "a b c"'),
        T("single_newline_is_space", 'assert wrap_text("one\\ntwo three", 80) == "one two three"'),
        T("paragraphs", 'assert wrap_text("a b\\n\\n\\n c d", 3) == "a b\\n\\nc d"'),
        T("whitespace_blank_line", 'assert wrap_text("x\\n   \\ny", 5) == "x\\n\\ny"'),
        T("long_word", 'assert wrap_text("abcdefghij", 4) == "abcd\\nefgh\\nij"'),
        T("long_word_pieces_are_words", 'assert wrap_text("xy abcdefg z", 4) == "xy\\nabcd\\nefg\\nz" and wrap_text("abcdef gh", 4) == "abcd\\nef\\ngh" and wrap_text("abcde f", 4) == "abcd\\ne f"'),
        T("empty_and_trim", 'assert wrap_text("   \\n  ", 5) == "" and wrap_text("\\n\\nhello\\n\\n", 5) == "hello"'),
        T("bad_width", _raises('wrap_text("abc", 0)', "ValueError")),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="orig_topo_order",
    suite="original",
    title="Dependency resolver with cycle reporting",
    entry_points=("topo_order", "CycleError"),
    prompt='''Write a Python dependency resolver.

    class CycleError(Exception)     # must have an attribute `cycle`
    topo_order(deps: dict[str, list[str]]) -> list[str]

`deps` maps each package to the list of packages it directly depends on.
Packages that appear only as dependencies are packages too.

1. Return a list containing every package exactly once, in which every
   package appears after all of its dependencies.
2. Among all valid orders, return the lexicographically smallest one: at
   each step, place the alphabetically smallest package whose dependencies
   have all been placed.
3. Duplicate entries in a dependency list are allowed and harmless.
4. If the dependencies contain a cycle, raise CycleError. Its `cycle`
   attribute must be a list [p0, p1, ..., pn] with p0 == pn and n >= 1, in
   which each p_i directly depends on p_(i+1). A package that depends on
   itself gives a cycle like ["a", "a"].
''',
    reference='''
import heapq
class CycleError(Exception):
    def __init__(self, cycle):
        super().__init__(" -> ".join(cycle))
        self.cycle = cycle

def topo_order(deps):
    graph = {}
    for p, ds in deps.items():
        graph.setdefault(p, set()).update(ds)
        for d in ds:
            graph.setdefault(d, set())
    # cycle detection via DFS (reports a concrete cycle)
    color, stack = {}, []
    def dfs(u):
        color[u] = 1; stack.append(u)
        for v in sorted(graph[u]):
            if color.get(v) == 1:
                i = stack.index(v)
                raise CycleError(stack[i:] + [v])
            if v not in color:
                dfs(v)
        stack.pop(); color[u] = 2
    for u in sorted(graph):
        if u not in color:
            dfs(u)
    remaining = {p: set(ds) for p, ds in graph.items()}
    users = {p: [] for p in graph}
    for p, ds in graph.items():
        for d in ds:
            users[d].append(p)
    heap = [p for p, ds in remaining.items() if not ds]
    heapq.heapify(heap)
    out = []
    while heap:
        p = heapq.heappop(heap)
        out.append(p)
        for u in users[p]:
            remaining[u].discard(p)
            if not remaining[u]:
                heapq.heappush(heap, u)
    return out
''',
    test_prelude='''
def _chk_order(order, deps):
    allp = set(deps) | {d for ds in deps.values() for d in ds}
    assert sorted(order) == sorted(allp), f"wrong package set: {order}"
    pos = {p: i for i, p in enumerate(order)}
    for p, ds in deps.items():
        for d in ds:
            assert pos[d] < pos[p], f"{d} must come before {p}"
    return True

def _chk_cycle(cyc, deps):
    assert isinstance(cyc, list) and len(cyc) >= 2 and cyc[0] == cyc[-1], f"bad cycle {cyc!r}"
    for a, b in zip(cyc, cyc[1:]):
        assert b in deps.get(a, []), f"{a} does not depend on {b}"
    return True
''',
    tests=(
        T("chain", 'assert topo_order({"app": ["lib"], "lib": ["core"]}) == ["core", "lib", "app"]'),
        T("lexicographic", 'assert topo_order({"b": [], "a": [], "c": []}) == ["a", "b", "c"]'),
        T("lex_smallest_not_dfs", 'deps = {"z": [], "a": ["z"], "b": []}\nassert topo_order(deps) == ["b", "z", "a"]'),
        T("dep_only_packages", 'deps = {"x": ["y", "w"]}\no = topo_order(deps)\nassert _chk_order(o, deps) and o == ["w", "y", "x"]'),
        T("diamond", 'deps = {"top": ["l", "r"], "l": ["base"], "r": ["base"]}\nassert topo_order(deps) == ["base", "l", "r", "top"]'),
        T("empty", 'assert topo_order({}) == []'),
        T("duplicates", 'deps = {"a": ["b", "b"], "b": []}\nassert topo_order(deps) == ["b", "a"]'),
        T("cycle_raises", 'deps = {"a": ["b"], "b": ["c"], "c": ["a"]}\ntry:\n    topo_order(deps); raise AssertionError("no CycleError")\nexcept CycleError as e:\n    assert _chk_cycle(e.cycle, deps)'),
        T("self_loop", 'try:\n    topo_order({"a": ["a"]}); raise AssertionError("no CycleError")\nexcept CycleError as e:\n    assert e.cycle == ["a", "a"]'),
        T("cycle_beside_dag", 'deps = {"ok": ["base"], "base": [], "p": ["q"], "q": ["r"], "r": ["q"]}\ntry:\n    topo_order(deps); raise AssertionError("no CycleError")\nexcept CycleError as e:\n    assert _chk_cycle(e.cycle, deps)'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="orig_undo_editor",
    suite="original",
    title="Text editor with undo/redo",
    entry_points=("Editor",),
    prompt='''Implement a Python class `Editor`: a one-line text buffer with a cursor
and undo/redo. It exposes read-only properties `text` (str) and `cursor`
(int); a new Editor has text "" and cursor 0.

    insert(s: str) -> None
    delete(n: int) -> None
    move(pos: int) -> None
    undo() -> bool
    redo() -> bool

Rules:
1. `insert(s)` inserts s at the cursor; the cursor moves to just after the
   inserted text.
2. `delete(n)` deletes up to n characters immediately BEFORE the cursor (like
   backspace) and moves the cursor left accordingly. If nothing would be
   deleted (cursor at 0 or n <= 0) it is a no-op and is not recorded in the
   undo history.
3. `move(pos)` sets the cursor to pos clamped to [0, len(text)]. Moves are
   not undoable actions and are never recorded in the history.
4. `undo()` reverts the most recent not-yet-undone insert/delete, restoring
   BOTH the text and the cursor to exactly what they were immediately before
   that edit. Returns True, or False if there is nothing to undo.
5. `redo()` re-applies the most recently undone edit, restoring the text and
   cursor to exactly what they were immediately after that edit. Returns True,
   or False if there is nothing to redo.
6. Any new recorded edit (insert or effective delete) clears the redo history.
''',
    reference='''
class Editor:
    def __init__(self):
        self._t, self._c = "", 0
        self._undo, self._redo = [], []
    @property
    def text(self):
        return self._t
    @property
    def cursor(self):
        return self._c
    def _record(self, before):
        self._undo.append((before, (self._t, self._c)))
        self._redo.clear()
    def insert(self, s):
        before = (self._t, self._c)
        self._t = self._t[:self._c] + s + self._t[self._c:]
        self._c += len(s)
        self._record(before)
    def delete(self, n):
        k = min(max(n, 0), self._c)
        if k == 0:
            return
        before = (self._t, self._c)
        self._t = self._t[:self._c - k] + self._t[self._c:]
        self._c -= k
        self._record(before)
    def move(self, pos):
        self._c = max(0, min(pos, len(self._t)))
    def undo(self):
        if not self._undo:
            return False
        before, after = self._undo.pop()
        self._t, self._c = before
        self._redo.append((before, after))
        return True
    def redo(self):
        if not self._redo:
            return False
        before, after = self._redo.pop()
        self._t, self._c = after
        self._undo.append((before, after))
        return True
''',
    tests=(
        T("insert", 'e = Editor()\ne.insert("hello")\nassert e.text == "hello" and e.cursor == 5'),
        T("insert_mid", 'e = Editor()\ne.insert("hd")\ne.move(1)\ne.insert("ello worl")\nassert e.text == "hello world" and e.cursor == 10'),
        T("backspace", 'e = Editor()\ne.insert("hello")\ne.move(3)\ne.delete(2)\nassert e.text == "hlo" and e.cursor == 1'),
        T("delete_clamps", 'e = Editor()\ne.insert("abc")\ne.delete(10)\nassert e.text == "" and e.cursor == 0'),
        T("move_clamps", 'e = Editor()\ne.insert("abc")\ne.move(-4)\nc1 = e.cursor\ne.move(99)\nassert c1 == 0 and e.cursor == 3'),
        T("undo_restores_cursor", 'e = Editor()\ne.insert("abc")\ne.insert("de")\ne.move(1)\nassert e.undo() is True and e.text == "abc" and e.cursor == 3'),
        T("undo_delete", 'e = Editor()\ne.insert("hello")\ne.delete(2)\ne.undo()\nassert e.text == "hello" and e.cursor == 5'),
        T("redo", 'e = Editor()\ne.insert("ab")\ne.move(0)\ne.insert("X")\ne.undo()\ne.move(2)\nassert e.redo() is True and e.text == "Xab" and e.cursor == 1 and e.redo() is False'),
        T("new_edit_clears_redo", 'e = Editor()\ne.insert("a")\ne.undo()\ne.insert("b")\nassert e.redo() is False and e.text == "b"'),
        T("noop_delete_not_recorded", 'e = Editor()\nassert e.undo() is False\ne.insert("x")\ne.move(0)\ne.delete(1)\nassert e.undo() is True and e.text == "" and e.undo() is False'),
    ),
))

# ---------------------------------------------------------------------------
TASKS.append(Task(
    task_id="orig_semver",
    suite="original",
    title="Semantic version precedence",
    entry_points=("compare_versions", "sort_versions"),
    prompt='''Write two Python functions implementing Semantic Versioning 2.0.0 precedence.

    compare_versions(a: str, b: str) -> int    # -1 if a < b, 0 if equal precedence, 1 if a > b
    sort_versions(versions: list[str]) -> list[str]   # ascending precedence, stable

Format: MAJOR.MINOR.PATCH, optionally followed by "-PRERELEASE" and/or
"+BUILD". PRERELEASE and BUILD are non-empty dot-separated identifiers made of
[0-9A-Za-z-]. Raise ValueError for invalid versions, including: missing parts
("1.0"), empty identifiers ("1.0.0-alpha..1"), and leading zeros in MAJOR,
MINOR, PATCH or in purely numeric prerelease identifiers ("01.0.0", "1.0.0-01").

Precedence:
1. Compare MAJOR, MINOR, PATCH numerically.
2. If those are equal, a version WITH a prerelease is lower than one without.
3. Compare prerelease identifiers left to right: numeric identifiers compare
   numerically; alphanumeric identifiers compare lexically by ASCII value;
   a numeric identifier is always lower than an alphanumeric one. If all
   compared identifiers are equal, the version with more identifiers is higher.
4. BUILD metadata is ignored for precedence. `sort_versions` must be stable,
   so versions with equal precedence keep their input order.
''',
    reference='''
import re, functools
_NUM = r"0|[1-9]\\d*"
_ID = r"[0-9A-Za-z-]+"
_RE = re.compile(rf"^({_NUM})\\.({_NUM})\\.({_NUM})(?:-({_ID}(?:\\.{_ID})*))?(?:\\+({_ID}(?:\\.{_ID})*))?$")
def _parse(v):
    m = _RE.match(v)
    if not m:
        raise ValueError(v)
    pre = m.group(4).split(".") if m.group(4) else []
    for p in pre:
        if p.isdigit() and len(p) > 1 and p[0] == "0":
            raise ValueError(v)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))), pre

def compare_versions(a, b):
    (ca, pa), (cb, pb) = _parse(a), _parse(b)
    if ca != cb:
        return -1 if ca < cb else 1
    if not pa or not pb:
        if pa == pb:
            return 0
        return -1 if pa else 1
    for x, y in zip(pa, pb):
        if x == y:
            continue
        xd, yd = x.isdigit(), y.isdigit()
        if xd and yd:
            return -1 if int(x) < int(y) else 1
        if xd != yd:
            return -1 if xd else 1
        return -1 if x < y else 1
    if len(pa) == len(pb):
        return 0
    return -1 if len(pa) < len(pb) else 1

def sort_versions(versions):
    return sorted(versions, key=functools.cmp_to_key(compare_versions))
''',
    tests=(
        T("numeric_core", 'assert compare_versions("1.2.10", "1.2.9") == 1 and compare_versions("1.9.0", "1.10.0") == -1'),
        T("prerelease_lower", 'assert compare_versions("1.0.0-alpha", "1.0.0") == -1 and compare_versions("1.0.0", "1.0.0-rc.1") == 1'),
        T("numeric_ids", 'assert compare_versions("1.0.0-alpha.2", "1.0.0-alpha.10") == -1'),
        T("numeric_lt_alpha", 'assert compare_versions("1.0.0-1", "1.0.0-alpha") == -1 and compare_versions("1.0.0-alpha.beta", "1.0.0-alpha.1") == 1'),
        T("longer_wins", 'assert compare_versions("1.0.0-alpha", "1.0.0-alpha.1") == -1'),
        T("ascii_lexical", 'assert compare_versions("1.0.0-Beta", "1.0.0-alpha") == -1 and compare_versions("1.0.0-a-b", "1.0.0-a") == 1'),
        T("build_ignored", 'assert compare_versions("1.0.0+build.1", "1.0.0+zzz") == 0 and compare_versions("1.0.0-rc.1+x", "1.0.0-rc.1") == 0'),
        T("spec_order", 'vs = ["1.0.0", "1.0.0-rc.1", "1.0.0-beta.11", "1.0.0-beta.2", "1.0.0-beta", "1.0.0-alpha.beta", "1.0.0-alpha.1", "1.0.0-alpha"]\nassert sort_versions(vs) == ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1", "1.0.0"]'),
        T("stable_sort", 'assert sort_versions(["2.0.0+b", "1.0.0", "2.0.0+a"]) == ["1.0.0", "2.0.0+b", "2.0.0+a"]'),
        T("invalid", "\n".join(_raises(f'compare_versions("{v}", "1.0.0")', "ValueError") for v in ["1.0", "01.0.0", "1.0.0-01", "1.0.0-alpha..1", "1.0.0-", "v1.0.0"])),
    ),
))
