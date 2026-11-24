#!/usr/bin/env python3
"""Is Vibecoding a Slot Machine? -- classroom demo.

    python demo/cli_demo.py --cached            # replay recorded experiment traces (no network)
    python demo/cli_demo.py --live              # real generations through the configured backend
    python demo/cli_demo.py --cached --task he_fix_spaces --script "r,r,r,e,1,2,3,4,c,q" --fast

Keys:  r  pull the lever (blind regenerate)     e  paste-the-error loop
       1  Patch 1 retry budget + handoff         2  Patch 2 hidden best-of-5
       3  Patch 3 test-gated reveal              4  Patch 4 typed holes
       c  compare all conditions (from results)  t  pick another task
       q  quit
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rich import box  # noqa: E402
from rich.align import Align  # noqa: E402
from rich.columns import Columns  # noqa: E402
from rich.console import Console, Group  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.prompt import Prompt  # noqa: E402
from rich.syntax import Syntax  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.text import Text  # noqa: E402

from harness.metrics import binary_entropy  # noqa: E402
from harness.store import JsonlStore  # noqa: E402
from tasks import get_task, load_tasks  # noqa: E402

RESULTS = ROOT / "results"
PATCH_KEYS = {"1": "retry_budget", "2": "hidden_best_of_n", "3": "test_gated_reveal", "4": "typed_holes_patch"}
PATCH_TITLES = {"slot_machine": "SLOT MACHINE MODE", "retry_budget": "PATCH 1 - Retry budget + decomposition handoff",
                "hidden_best_of_n": "PATCH 2 - Hidden best-of-5 + behavioural diff",
                "test_gated_reveal": "PATCH 3 - Test-gated reveal + diagnosis",
                "typed_holes_patch": "PATCH 4 - Spec-first typed holes"}
OUTCOME_STYLE = {"pass": ("JACKPOT  all tests pass", "bold black on green"),
                 "near_miss": ("SO CLOSE  near-miss", "bold black on dark_orange"),
                 "fail": ("MISS", "bold white on red")}
# Tasks that behave most like slot machines in the recorded data (good live picks).
SUGGESTED = ["he_fix_spaces", "orig_vending_machine", "orig_wrap_text", "orig_parser_combinators",
             "mbpp_parse_kv", "he_make_palindrome"]


class Demo:
    def __init__(self, console: Console, mode: str, delay: float, keys: list[str] | None,
                 backend: str = "auto", model: str = "haiku"):
        self.c = console
        self.mode = mode
        self.delay = delay
        self.keys = keys
        self.task = None
        self.pulls: list[str] = []
        self.counters = Counter()
        self.client = None
        self.backend, self.model = backend, model
        self._blind = {}
        self._ep = {}
        self._p2 = {}
        self.reroll_hazard = None
        p1 = RESULTS / "summary" / "phase1_vibe.json"
        if p1.exists():
            self.reroll_hazard = json.loads(p1.read_text())["blind_curve"]["hazard"][1]
        if mode == "cached":
            self._load_cache()

    # ---- data --------------------------------------------------------------
    def _load_cache(self):
        for r in JsonlStore(RESULTS / "phase1" / "vibe" / "blind.jsonl").load():
            self._blind.setdefault(r["task_id"], {})[r["chain"]] = r
        for r in JsonlStore(RESULTS / "phase1" / "vibe" / "error_paste.jsonl").load():
            self._ep.setdefault(r["task_id"], {}).setdefault(r["chain"], []).append(r)
        for path in sorted((RESULTS / "phase2").glob("*.jsonl")):
            for r in JsonlStore(path).load():
                cond = r["condition"]
                self._p2.setdefault((cond, r["task_id"]), {})[(r.get("variant", cond), r["session"])] = r
        if not self._blind:
            self.c.print("[red]No recorded traces in results/. Run the experiments or use --live.[/]")
            sys.exit(1)

    def _live_client(self):
        if self.client is None:
            from harness.llm_client import LLMClient, make_backend
            self.client = LLMClient(make_backend(self.backend, self.model), RESULTS / "raw" / "demo_calls.jsonl")
        return self.client

    def _fresh(self) -> int:
        self.counters["fresh"] += 1
        return 100_000 + int(time.time()) % 100_000 * 10 + self.counters["fresh"]

    # ---- input ---------------------------------------------------------------
    def ask(self, prompt: str, default: str = "") -> str:
        if self.keys is not None:
            if not self.keys:
                return "q"
            k = self.keys.pop(0)
            self.c.print(f"[dim]{prompt} > {k}[/]")
            return k
        return Prompt.ask(prompt, default=default)

    def pause(self, s: float = 1.0):
        if self.delay:
            time.sleep(s * self.delay)

    # ---- rendering helpers -----------------------------------------------------
    def header(self, title: str, style: str = "bold white on dark_red"):
        self.c.rule(Text(f"  {title}  ", style=style))

    def test_strip(self, rec_or_event: dict, n_total: int) -> Text:
        failed = set(rec_or_event.get("failed_tests") or [])
        t = Text()
        for tc in self.task.tests[:n_total]:
            t.append("■", style="red" if tc.name in failed else "green")
            t.append(" ")
        return t

    def code(self, src: str, max_lines: int = 22, title: str = "generated code"):
        lines = src.rstrip().splitlines()
        shown = "\n".join(lines[:max_lines]) + (f"\n# ... {len(lines) - max_lines} more lines" if len(lines) > max_lines else "")
        self.c.print(Panel(Syntax(shown, "python", theme="ansi_dark", line_numbers=False, word_wrap=True),
                           title=title, border_style="grey50", box=box.ROUNDED))

    def outcome_banner(self, outcome: str, n_pass: int, n_total: int):
        label, style = OUTCOME_STYLE[outcome]
        self.c.print(Align.center(Text(f"  {label}   {n_pass}/{n_total} tests  ", style=style)))

    def meter(self):
        """Variance meter + dopamine-loop diagnostics for the pulls seen so far."""
        n = len(self.pulls)
        if not n:
            return
        k = sum(o == "pass" for o in self.pulls)
        nm = sum(o == "near_miss" for o in self.pulls)
        p = k / n
        H = binary_entropy(p)
        bar = Text()
        for o in self.pulls[-30:]:
            bar.append("●", style={"pass": "green", "near_miss": "dark_orange", "fail": "red"}[o])
        width = 24
        hbar = Text("█" * round(H * width), style="magenta") + Text("░" * (width - round(H * width)), style="grey35")
        streak = 0
        for o in reversed(self.pulls):
            if o == "pass":
                break
            streak += 1
        t = Table.grid(padding=(0, 2))
        t.add_row("pulls", str(n), "history", bar)
        t.add_row("hit rate", f"{p:.0%}", "entropy H", hbar + Text(f" {H:.2f} bits"))
        t.add_row("near-misses", f"{nm}  ({nm / max(1, n - k):.0%} of misses)", "losing streak", str(streak))
        msg = ""
        if self.pulls[-1] == "near_miss":
            msg = "Near-miss: one more pull feels like it will win."
            if self.reroll_hazard is not None:
                msg += (f" In the recorded data, a blind re-roll after a miss passes only "
                        f"{self.reroll_hazard:.0%} of the time.")
        elif 0 < p < 1:
            msg = "Intermittent payout: variable-ratio reinforcement, the schedule most resistant to extinction."
        self.c.print(Panel(Group(t, Text(msg, style="italic yellow") if msg else Text("")),
                           title="variance meter / dopamine-loop diagnostics", border_style="magenta"))

    # ---- actions -------------------------------------------------------------------
    def pick_task(self):
        tasks = load_tasks()
        table = Table(box=box.SIMPLE_HEAD, show_edge=False)
        table.add_column("#", justify="right")
        table.add_column("task")
        table.add_column("suite")
        table.add_column("request a vibecoder types", overflow="fold")
        for i, t in enumerate(tasks, 1):
            mark = "[bold yellow]*[/]" if t.task_id in SUGGESTED else ""
            table.add_row(str(i), t.task_id + mark, t.suite, t.vibe_prompt[:70] + ("..." if len(t.vibe_prompt) > 70 else ""))
        self.c.print(table)
        self.c.print("[yellow]*[/] = behaves most like a slot machine in our recorded runs")
        ans = self.ask("task number or id", "2")
        try:
            self.task = tasks[int(ans) - 1]
        except (ValueError, IndexError):
            self.task = get_task(ans)
        self.pulls = []
        self.counters = Counter()
        self.show_task()

    def show_task(self):
        self.header(f"TASK  {self.task.task_id}", "bold black on cyan")
        self.c.print(Panel(self.task.vibe_prompt, title="what the programmer typed", border_style="cyan"))
        self.c.print(f"[dim]{self.task.n_tests} hidden tests encode what they actually meant.[/]")

    def pull(self):
        self.header(PATCH_TITLES["slot_machine"])
        if self.mode == "cached":
            recs = self._blind.get(self.task.task_id, {})
            j = self.counters["pull"] % max(1, len(recs))
            r = recs[sorted(recs)[j]]
            code, outcome, n_pass, n_total, failed = r["code"], r["outcome"], r["n_pass"], r["n_total"], r
            with self.c.status("[bold]pulling the lever...", spinner="dots"):
                self.pause(1.2)
        else:
            from harness.prompts import task_prompt
            from harness.runner import generate_and_test
            with self.c.status("[bold]pulling the lever (live)...", spinner="dots"):
                g = generate_and_test(self._live_client(), self.task, task_prompt(self.task), self._fresh(), "demo_pull")
            code, outcome, n_pass, n_total = g.code, g.outcome, g.result.n_pass, g.result.n_total
            failed = {"failed_tests": [o.name for o in g.result.failed()]}
        self.counters["pull"] += 1
        self.code(code)
        self.c.print(Align.center(self.test_strip(failed, n_total)))
        self.outcome_banner(outcome, n_pass, n_total)
        self.pulls.append(outcome)
        self.meter()

    def error_paste(self):
        self.header("SLOT MACHINE MODE - paste the error, ask for a fix")
        if self.mode == "cached":
            chains = self._ep.get(self.task.task_id, {})
            # Prefer a chain that starts with a failure: that is where the loop is visible.
            order = sorted(chains, key=lambda c: (chains[c][0]["outcome"] == "pass", c))
            ch = chains[order[self.counters["ep"] % len(order)]]
            turns = [(r["code"], r["outcome"], r["n_pass"], r["n_total"], r) for r in ch]
        else:
            from harness.patches import Ctx, slot_machine
            with self.c.status("[bold]running a live error-paste session...", spinner="dots"):
                s = slot_machine(Ctx(self._live_client()), self.task, self._fresh()).to_dict()
            turns = [(None, e["outcome"], e["n_pass"], e["n_total"], e) for e in s["events"]]
        self.counters["ep"] += 1
        for i, (code, outcome, n_pass, n_total, r) in enumerate(turns, 1):
            self.c.print(f"[bold]turn {i}[/]  " + ("generate" if i == 1 else "[dim]user pastes pytest output: 'Please fix it.'[/]"))
            if code:
                self.code(code, max_lines=14, title=f"turn {i}")
            self.c.print(Align.center(self.test_strip(r, n_total)))
            self.outcome_banner(outcome, n_pass, n_total)
            self.pulls.append(outcome)
            self.pause(1.0)
        self.c.print("[italic]The programmer was a courier between the test runner and the model: "
                     "zero decisions made, zero lines written.[/]")
        self.meter()

    def run_patch(self, cond: str):
        self.header(PATCH_TITLES[cond], "bold black on green3")
        if self.mode == "cached":
            sessions = self._p2.get((cond, self.task.task_id), {})
            if not sessions:
                self.c.print("[red]No recorded session for this task/patch.[/]")
                return
            # Prefer sessions where the intervention actually engaged (e.g. a P1 handoff,
            # which at the calibrated k=3 is rare; the k-sweep variants supply them).
            def engaged(key):
                r = sessions[key]
                return (r["extra"].get("handoff", False) or r["decision_points"] > 0, len(r["events"]))
            order = sorted(sessions, key=lambda key: (engaged(key), -key[1]), reverse=True)
            s = sessions[order[self.counters[cond] % len(order)]]
            if cond == "retry_budget":
                self.c.print(f"[dim]retry budget k = {s.get('k')} (recorded variant {s.get('variant')})[/]")
        else:
            from harness.patches import Ctx, run_condition
            k = json.loads((RESULTS / "phase2" / "meta.json").read_text()).get("k_star", 3) \
                if (RESULTS / "phase2" / "meta.json").exists() else 3
            with self.c.status(f"[bold]running {cond} live (several model calls)...", spinner="dots"):
                s = run_condition(Ctx(self._live_client(), pool_size=10 ** 9), cond, self.task, self._fresh(), k).to_dict()
        self.counters[cond] += 1
        for e in s["events"]:
            self.render_event(e, s)
            self.pause(1.0)
        self.scorecard(s)

    def render_event(self, e: dict, s: dict):
        k = e["kind"]
        if k == "code":
            self.c.print(f"[bold]automatic attempt {e.get('turn', '')}[/] (shown)")
            self.c.print(Align.center(self.test_strip(e, e["n_total"])))
            self.outcome_banner(e["outcome"], e["n_pass"], e["n_total"])
        elif k == "best_of_n":
            hidden = e.get("hidden_outcomes", [])
            self.c.print(f"[bold]round {e.get('round')}[/]: {len(hidden)} candidates generated and tested "
                         "[italic]privately[/] -- you never see the near-misses")
            self.c.print(Align.center(Text("▢ " * len(hidden), style="grey50")))
            self.c.print(Panel(e.get("diff", ""), title="behavioural diff of hidden candidates", border_style="green"))
            self.outcome_banner(e["outcome"], e["n_pass"], e["n_total"])
        elif k == "hidden_attempt":
            self.c.print(Panel(Text("Code withheld: this attempt does not pass your tests.\n"
                                    "No score, no almost-working code to tweak.", style="bold"),
                               title=f"attempt {e.get('turn')}  [locked]", border_style="red"))
        elif k == "diagnosis":
            self.c.print(Panel(Text(e["text"]), title="diagnosis (no code) -> add to your spec?", border_style="yellow"))
            self.c.print("[dim]programmer accepts the clarification as part of their spec[/]")
        elif k == "revealed":
            self.c.print("[bold green]All tests pass: code revealed.[/]")
            if s.get("final_code"):
                self.code(s["final_code"], max_lines=16, title="revealed")
        elif k == "scaffold":
            title = "decomposition handoff" if s["condition"] == "retry_budget" else "spec-first skeleton"
            self.c.print(f"[bold]{title}[/]: agent wrote the API, boilerplate and "
                         f"{e['n_invariants']} executable invariants "
                         f"({e['invariants_valid_ref']} hold on the reference)")
            if s.get("final_code"):
                skel = s["final_code"].split("# ---- holes filled by the programmer ----")[0]
                self.code(skel, max_lines=26, title="skeleton (holes = your decisions)")
            holes = Table(box=box.SIMPLE, title="your decisions")
            holes.add_column("typed hole")
            for h in e.get("holes", []):
                holes.add_row(f"[bold yellow]{h}[/]")
            self.c.print(holes)
        elif k == "human_fill":
            who = "programmer (simulated in this replay)" if self.mode == "cached" else "programmer (simulated)"
            self.c.print(f"[bold]{who} fills the holes, round {e.get('round')}[/]: {e.get('fill_lines', 0)} lines")
            self.c.print(Align.center(self.test_strip(e, e["n_total"])))
            self.outcome_banner(e["outcome"], e["n_pass"], e["n_total"])

    def scorecard(self, s: dict):
        t = Table(box=box.MINIMAL_HEAVY_HEAD, title="session scorecard")
        for col in ("final pass", "lottery outcomes shown", "near-misses shown", "passive retries",
                    "your decisions", "your lines", "agent calls"):
            t.add_column(col, justify="center")
        t.add_row("yes" if s["final_pass"] else "no", str(s["n_pulls"]), str(s["visible_near_misses"]),
                  str(s["passive_retries"]), str(s["decision_points"]),
                  f"{s['human_lines']}/{s['total_lines']}", str(s["agent_calls"]))
        self.c.print(t)

    def compare(self):
        p = RESULTS / "summary" / "phase2.json"
        if not p.exists():
            self.c.print("[red]Run `python -m analysis.phase2` first.[/]")
            return
        d = json.loads(p.read_text())
        short = {"slot_machine": "baseline", "retry_budget": "P1 budget k=3", "retry_budget_k1": "P1 budget k=1",
                 "retry_budget_k2": "P1 budget k=2", "hidden_best_of_n": "P2 best-of-5",
                 "test_gated_reveal": "P3 gated", "typed_holes_patch": "P4 holes"}
        t = Table(title="All 30 tasks, recorded experiment", box=box.SIMPLE_HEAVY)
        t.add_column("condition", no_wrap=True)
        for col in ("pass", "visible H", "near-misses", "passive retries", "decisions",
                    "human lines", "calls", "tokens"):
            t.add_column(col, justify="right")
        names = d["order"] + [n for n in ("retry_budget_k1", "retry_budget_k2") if n in d["variants"]]
        for name in names:
            v = d["variants"][name]
            t.add_row(short.get(name, name), f"{v['final_pass_rate']:.0%}", f"{v['visible_entropy_bits']:.2f}",
                      f"{v['visible_near_misses_per_session']:.2f}", f"{v['passive_retries_per_session']:.2f}",
                      f"{v['decision_points_per_session']:.2f}", f"{v['human_line_frac']:.0%}",
                      f"{v['agent_calls_per_session']:.1f}", f"{v['agent_tokens_per_session'] / 1000:.1f}k")
        self.c.print(t)
        p3 = RESULTS / "summary" / "phase3.json"
        if p3.exists():
            d3 = json.loads(p3.read_text())
            t3 = Table(title=f"Realistic feedback: the programmer sees only {d3['meta'].get('n_visible', 3)} tests per task",
                       box=box.SIMPLE_HEAVY)
            t3.add_column("condition", no_wrap=True)
            for col in ("intent pass", "silent failure", "vs vibecoder", "near-misses", "decisions", "turns", "tokens"):
                t3.add_column(col, justify="right")
            for name in d3["order"]:
                v = d3["variants"][name]
                dl = v.get("delta_intent_vs_vibecoder") or {}
                delta = "--" if name == "slot_machine" or dl.get("delta") is None else \
                    f"{100 * dl['delta']:+.0f} [{100 * dl['lo']:+.0f}, {100 * dl['hi']:+.0f}]"
                t3.add_row(d3["labels"].get(name, name), f"{v['intent_pass_rate']:.0%}", f"{v['silent_failure_rate']:.0%}",
                           delta, f"{v['visible_near_misses_per_session']:.2f}", f"{v['decision_points_per_session']:.2f}",
                           f"{v['human_turns_per_session']:.2f}", f"{v['agent_tokens_per_session'] / 1000:.1f}k")
            self.c.print(t3)

    # ---- main loop -----------------------------------------------------------
    def run(self, task_id: str | None):
        self.c.print(Panel(Align.center(Text("IS VIBECODING A SLOT MACHINE?\n", style="bold") +
                                        Text("measuring the reward structure of AI coding agents\n"
                                             "and testing agency-preserving 'nicotine patches'", style="italic")),
                           border_style="dark_red", subtitle=f"mode: {self.mode}"))
        if task_id:
            self.task = get_task(task_id)
            self.show_task()
        else:
            self.pick_task()
        actions = {"r": self.pull, "e": self.error_paste, "c": self.compare, "t": self.pick_task}
        while True:
            self.c.print(Columns([Text("[r] pull lever", style="bold red"), Text("[e] paste error"),
                                  Text("[1] P1 budget"), Text("[2] P2 best-of-5"), Text("[3] P3 gated"),
                                  Text("[4] P4 holes"), Text("[c] compare"), Text("[t] task"), Text("[q] quit")]))
            key = self.ask("action", "r").strip().lower()
            if key == "q":
                break
            if key in PATCH_KEYS:
                self.run_patch(PATCH_KEYS[key])
            elif key in actions:
                actions[key]()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--cached", "--replay", dest="cached", action="store_true", default=True,
                   help="replay recorded traces (default, deterministic, offline)")
    g.add_argument("--live", dest="cached", action="store_false", help="real generations")
    ap.add_argument("--task", default=None)
    ap.add_argument("--script", default=None, help="comma-separated key presses (non-interactive)")
    ap.add_argument("--fast", action="store_true", help="no presentation pauses")
    ap.add_argument("--backend", default="auto")
    ap.add_argument("--model", default="haiku")
    args = ap.parse_args(argv)
    keys = [k.strip() for k in args.script.split(",")] if args.script is not None else None
    demo = Demo(Console(), "cached" if args.cached else "live", 0 if args.fast else 1.0, keys,
                args.backend, args.model)
    demo.run(args.task)


if __name__ == "__main__":
    main()
