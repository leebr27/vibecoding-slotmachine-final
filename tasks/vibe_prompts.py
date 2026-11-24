"""Terse "vibe" requests: what a user types into a coding agent.

Each one names the API (so tests can call it) and states the core intent in
one to three sentences, but leaves most edge-case rules implicit. The hidden
test suite still encodes the full intent (the detailed `Task.prompt`), so the
gap between the two is the specification gap a vibecoder leaves open.
"""

VIBE_PROMPTS: dict[str, str] = {
    # --- HumanEval-derived ---
    "he_make_palindrome": "Write `make_palindrome(s)` that returns the shortest palindrome that starts with s, by adding characters to the end.",
    "he_fix_spaces": "Write `fix_spaces(text)`: replace spaces with underscores, but if there are lots of consecutive spaces, replace the whole run with a single '-'.",
    "he_minpath": "Write `minPath(grid, k)`: grid is NxN containing the numbers 1..N*N. Return the lexicographically smallest list of values along a path of k cells, moving between edge-adjacent cells (cells may be revisited).",
    "he_tri": "Write `tri(n)` returning [t(0), ..., t(n)] for the sequence t(0)=1, t(1)=3, t(k)=1+k/2 for even k, and t(k)=t(k-1)+t(k-2)+t(k+1) for odd k.",
    "he_is_nested": "Write `is_nested(s)` for a string of square brackets: return True if there is a valid subsequence of brackets in which at least one bracket is nested.",
    "he_file_name_check": "Write `file_name_check(name)` returning 'Yes' or 'No'. A valid name has at most 3 digits, exactly one dot, a part before the dot that starts with a letter, and an extension of txt, exe or dll.",
    "he_order_by_points": "Write `order_by_points(nums)` that sorts integers by the sum of their digits (for negative numbers the first digit counts as negative), keeping the original order for ties.",
    "he_do_algebra": "Write `do_algebra(operators, operands)` that builds an expression from a list of operators (+, -, *, //, **) and a list of operands and evaluates it with normal precedence, without using eval.",
    "he_compare_one": "Write `compare_one(a, b)` that takes ints, floats or numeric strings (which may use a comma as the decimal point) and returns the larger one in its original type, or None if they are equal.",
    "he_numerical_letter_grade": "Write `numerical_letter_grade(grades)` that converts a list of GPAs to letter grades on the usual scale: 4.0 is A+, above 3.7 is A, above 3.3 is A-, above 3.0 is B+, and so on down to D- for anything above 0.0, and E for 0.0.",
    # --- MBPP-style ---
    "mbpp_remove_occ": "Write `remove_occ(s, ch)` that removes the first and last occurrence of a character from a string.",
    "mbpp_sort_matrix": "Write `sort_matrix(m)` that sorts the rows of a matrix in ascending order of their sums.",
    "mbpp_rle": "Write `compress(s)` and `decompress(s)` for run-length encoding of strings of letters, e.g. 'aaabcc' <-> 'a3bc2'.",
    "mbpp_top_k_words": "Write `top_k_words(text, k)` that returns the k most common words in a text as (word, count) tuples, case-insensitive, most frequent first.",
    "mbpp_normalize_phone": "Write `normalize_phone(s)` that formats a US phone number as '(XXX) XXX-XXXX'. Accept the common input formats (including an optional +1) and raise ValueError for invalid numbers.",
    "mbpp_flatten": "Write `flatten(nested)` that flattens arbitrarily nested lists and tuples into a single flat list (strings should stay whole).",
    "mbpp_roman": "Write `to_roman(n)` and `from_roman(s)` for Roman numerals from 1 to 3999. Both should raise ValueError on invalid input.",
    "mbpp_merge_intervals": "Write `merge_intervals(intervals)` that merges overlapping [start, end] intervals and returns the result sorted.",
    "mbpp_parse_kv": "Write `parse_kv(line)` that parses a config line like 'a=1; debug; msg=\"hi; there\"' into a dict. Bare keys map to True and quoted values can contain semicolons.",
    "mbpp_column_stats": "Write `column_stats(csv_text, column)` that returns a dict with the count, sum, mean, min and max of a numeric column in CSV text with a header row, skipping empty cells.",
    # --- original ---
    "orig_ttl_cache": "Write a `TTLCache(capacity, ttl)` class: an LRU cache whose entries expire ttl seconds after they are written. Methods: put(key, value, now), get(key, now) returning None if missing or expired, and size(now). The current time is always passed in as `now`.",
    "orig_mini_interpreter": "Write `evaluate(expr)` that evaluates integer arithmetic expressions with + - * / % ^, unary minus and parentheses, without using eval. Use C-style integer division (truncate toward zero). Raise SyntaxError for malformed input.",
    "orig_vending_machine": "Write a `VendingMachine(prices, coins)` class (prices: item -> cents, coins: coin inventory for change) with insert(coin) -> bool (accepts 5, 10 and 25), balance(), select(item) and cancel(). select returns the change as a list of coins using the fewest coins from the machine's inventory, or one of the strings 'UNKNOWN', 'INSUFFICIENT' or 'NO_CHANGE'; cancel returns the inserted coins.",
    "orig_parser_combinators": "Write a tiny parser-combinator library. A parser is a function (s, i) -> (value, new_i), or None on failure. Provide char, string, satisfy, seq, alt, many, sep_by, map_, a ParseError exception with a pos attribute, and parse(p, s), which must consume the whole input.",
    "orig_interval_scheduler": "Write a `Scheduler` class for booking one room using half-open intervals [start, end): book(start, end) -> bool (False if it overlaps), cancel(start, end) -> bool, bookings() returning a sorted list of tuples, and free_slots(lo, hi, min_len=1) listing the free gaps inside a window.",
    "orig_graph_coloring": "Write `color_graph(nodes, edges, k, precolored=None)` that returns a dict assigning every node a color 0..k-1 so adjacent nodes get different colors (keeping any precolored nodes fixed), or None if that is impossible.",
    "orig_wrap_text": "Write `wrap_text(text, width)` that greedily word-wraps text to the given width, keeping paragraphs (separated by blank lines) separate.",
    "orig_topo_order": "Write `topo_order(deps)` that takes {package: [dependencies]} and returns an install order with dependencies first, breaking ties alphabetically. Raise a `CycleError` (with a `.cycle` list attribute) if there is a cycle.",
    "orig_undo_editor": "Write an `Editor` class with `text` and `cursor` properties and methods insert(s), delete(n) (backspace), move(pos), undo() and redo(); undo and redo return True or False depending on whether they did anything.",
    "orig_semver": "Write `compare_versions(a, b)` (returning -1, 0 or 1) and `sort_versions(versions)` following the Semantic Versioning 2.0.0 precedence rules. Raise ValueError for invalid versions.",
}
