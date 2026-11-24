# Is Vibecoding a Slot Machine?

**Measuring the reward structure of AI coding agents, and testing agency-preserving "nicotine patches."**
The paper is in [`report/report.pdf`](report/report.pdf).

## Key findings

Model: Claude Haiku 5.5 via `claude -p`. The study made 2,582 logged calls (8.1M tokens), costing $3.16 at
list prices.

**Phase 1: is it a slot machine?** We ran 300 blind pulls (30 tasks × 10) using terse "vibe" prompts.

* 77% of pulls pass. **84% of failures are near-misses** (at least 80% of tests passing), and the
  median failure passes 90% of its tests.
* The near-misses are systematic. Ten pulls of the same prompt show only **1.43 distinct behaviours**
  per task, even though their code text is only 50% similar.
* **The variance comes from the specification gap, not the sampler.** The same tasks written as full
  specifications pass **300/300**.
* Blind re-rolling decays fast: 24% success on the 2nd pull and 7% on the 5th. Pasting the pytest error back
  works 91% of the time, because the failure output carries the missing intent. The human only carries it.

**Phase 2: nicotine patches with complete test feedback** (10 sessions per task; P4 uses 5)

| condition | pass | visible near-misses / session | human decisions / session | agent tokens |
|---|---|---|---|---|
| slot machine (error-paste) | 100% | 0.21 | 0 | 1.0× |
| P1 retry budget, k=3 (calibrated) | 100% | 0.21 | 0 | 1.0× |
| P1 retry budget, k=1 | 98% | 0.19 | 0.41 | 1.1× |
| P2 hidden best-of-5 + behavioural diff | 100% | 0.11 | 0 | 4.1× |
| P3 test-gated reveal + code-free diagnosis | 99% | **0** | 0.30 | 1.2× |
| P4 spec-first typed holes | 85% | **0** | **2.19** | 1.6× |

With complete tests, no patch can beat the baseline on success: every failure report already contains the
expected values, so the model is handed the intent. The patches can only trade success for agency.

**Phase 3: the same patches with realistic feedback.** The programmer owns only the first 3 tests of each
task (all feedback comes from those; the rest are held out for scoring), and the simulated programmer
privately knows the full specification.

| condition | intent pass [95% CI] | vs vibecoder, pts [95% CI] | silent failures | decisions / session |
|---|---|---|---|---|
| vibecoder (paste errors) | 78% [65, 90] | | 22% | 0 |
| attentive programmer (upper bound) | 100% | +22 [+10, +35] | 0% | 0.56 |
| P1 retry budget, k=1 | 79% | +1 [0, +2] | 21% | 0.05 |
| P2 hidden best-of-5 | 78% | 0 | 22% | 0 |
| P3 test-gated reveal | 78% | 0 | 22% | 0.04 |
| P4 typed holes | 87% | +9 [−3, +22] | 12% | 2.19 |
| **P4 + hole requests** | **95%** | **+16 [+5, +30]** | **5%** | 2.48 |

* **The baseline's 100% was an artifact of complete tests.** With its own 3 tests, the vibecoder ships code
  that passes them and is wrong in 22% of sessions (54% wrong on the 12 contested tasks). The near-miss
  becomes a loss disguised as a win.
* **Failure-triggered patches inherit the blind spot.** P1, P2 and P3 act only when a test fails, and the
  programmer's tests flagged just 10 of 300 first attempts.
* **Asking before generating helps once the programmer can reopen the scaffold.** P4 with hole requests (the
  programmer may name a decision the skeleton fixed in boilerplate; the agent re-scaffolds once) is the only
  patch with a reliable gain, +7 points over plain P4, recovering most of the attentive programmer's gain.

The full tables are in `report/report.pdf`; the raw numbers are in `results/summary/*.json`.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                                   # benchmark validation, sandbox, harness, patches, demo
python demo/cli_demo.py --cached            # classroom demo, replays recorded traces (offline)
```

## Classroom demo

```bash
python demo/cli_demo.py --cached                      # pick a task interactively
python demo/cli_demo.py --cached --task he_fix_spaces # jump straight to a task
python demo/cli_demo.py --live --task orig_wrap_text  # real generations (needs a backend)
```

| key | action |
|---|---|
| `r` | pull the lever: one blind regeneration (code, test strip, JACKPOT / SO CLOSE / MISS banner, variance meter) |
| `e` | the paste-the-error loop, turn by turn |
| `1`..`4` | run Patch 1-4 on the current task and show what the programmer would see, plus a session scorecard |
| `c` | comparison table for all conditions over all 30 tasks |
| `t` / `q` | change task / quit |

`--cached` (alias `--replay`) uses only `results/`, so it is deterministic and needs no network.

### Browser version

```bash
python demo/web_demo.py            # serves http://127.0.0.1:8765 and opens it; replays results/ offline
python demo/web_demo.py --live     # also enables the "Live" toggle (real model calls)
```

The same keys work in the browser (`R`, `E`, `1`..`4`, `C`, `T`), plus `O` for the Phase 1 overview,
`P` to peek behind the glass, `[` / `]` to step through tasks, and `F` to switch between **All tests**
(Phase 2, complete feedback) and **Your 3 tests** (Phase 3, realistic feedback). In realistic mode the
held-out tests are veiled until you press `P`, each session ends with a "Shipped" card that reveals
whether the code was actually right, and the Paste tab can replay the vibecoder or the attentive
programmer. The server uses
only the standard library, binds to localhost, and serves read-only data from `results/`. Fonts load
from Google Fonts when online and fall back to system fonts offline. Append `?fast` to the URL to
shorten the animations for a rehearsal.
Good tasks for showing slot-machine behaviour are starred in the task picker
(`he_fix_spaces`, `orig_vending_machine`, `orig_wrap_text`, `orig_parser_combinators`, `mbpp_parse_kv`).
`--script "r,r,e,3,4,c,q" --fast` runs a fixed key sequence without prompts (useful for rehearsal).

## Reproducing the experiments

The default backend is the Claude Code CLI (`claude -p`), which uses whatever authentication Claude Code
already has. No API key is required. If `claude` is not on `PATH`, the client looks inside the VS Code
extension directory, or you can set `CLAUDE_BIN`. Other backends: `--backend ollama` (local, auto-detected
at `localhost:11434`), `--backend anthropic` (`ANTHROPIC_API_KEY`), or `--backend openai` (`OPENAI_API_KEY`).

```bash
python -m harness.runner --prompt-style vibe --trials 10 --chains 10 --max-turns 5 --workers 6   # Phase 1
python -m harness.runner --prompt-style spec --trials 10 --chains 10 --max-turns 5 --workers 6   # control
python -m analysis.phase1 --style vibe && python -m analysis.phase1 --style spec               # stats + k*
python -m harness.evaluate --workers 6                                                          # Phase 2
python -m harness.evaluate --variants retry_budget:1,retry_budget:2                             # P1 k-sweep
python -m harness.evaluate_realistic --workers 8                                                # Phase 3
python -m analysis.phase2 && python -m analysis.phase3
python -m analysis.plots && python -m analysis.report_numbers
cd report && latexmk -pdf report.tex
```

Runs are checkpointed: every model call is appended to `results/raw/llm_calls.jsonl`, which doubles as
a cache keyed by (backend, model, system prompt, prompt, sample index). An interrupted run resumes where
it stopped, and re-running against the committed log reproduces every result without new model calls.
With a different backend or model the cache misses and fresh samples are drawn.

## Layout

```
tasks/        30 tasks: humaneval_tasks.py, mbpp_tasks.py, original_tasks.py, vibe_prompts.py
harness/      sandbox.py (isolated test execution), llm_client.py (backends + call log),
              runner.py (Phase 1 regimes), patches.py (baseline + 4 patches), evaluate.py (Phase 2),
              realistic.py + evaluate_realistic.py (Phase 3: visible vs held-out tests),
              metrics.py (classification, entropy, retry curves, bootstrap), prompts.py, codeutil.py
analysis/     phase1.py, phase2.py, phase3.py, plots.py, report_numbers.py
results/      raw/llm_calls.jsonl (every call: prompt, response, tokens, cost, latency),
              phase1/{vibe,spec}/*.jsonl, phase2/*.jsonl, phase3/*.jsonl, summary/*.json
figures/      fig1_variance_and_nearmiss, fig2_retry_curves, fig3_patch_tradeoffs (.pdf, .png)
report/       report.tex, refs.bib, generated numbers.tex, table_patches.tex, table_realistic.tex, report.pdf
demo/         cli_demo.py (terminal), web_demo.py + web/ (browser, localhost)
tests/        pytest suite
```

## Definitions in one place

* **Pass**: all tests pass. **Near-miss**: the code loads and at least 80% of tests pass, or exactly one
  test fails. **Fail**: anything else, including syntax errors and crashes on import.
* **Outcome entropy**: binary entropy of a task's empirical pass rate over N=10 pulls.
* **Marginal retry curve**: P(pass at attempt t | attempts 1..t-1 failed). This is a plug-in i.i.d.
  estimate pooled over tasks for blind re-rolls, and empirical for error-paste chains.
* **Visible entropy / near-misses**: computed over what the programmer is shown, not over what the model
  generated.
* **Decision points**: typed holes the programmer fills, or clarifications they accept.
* **Visible / held-out tests (Phase 3)**: the programmer owns the first 3 tests of each task (a rule fixed
  before any run); all feedback comes from those. The rest are held out and only score the final program.
* **Intent pass**: the final program passes the full suite. **Silent failure**: it passes every visible test
  but not the full suite, so it looks finished and is wrong.

## Caveats

* One model (Claude Haiku 5.5 via Claude Code), 30 Python tasks, intent defined by hidden tests.
* The tasks, tests, reference solutions and vibe prompts were written by an AI assistant (Claude) for this
  study, not collected from real programmers. Every reference passes its suite; no person reviewed every task.
* Where a protocol hands work to the programmer, a separately prompted model call stands in for the
  human (logged with tag `human_proxy_*` and excluded from agent cost). This shows a protocol *can* be
  completed within its boundaries. It is not a user study; `report/report.pdf` §6 sketches the study
  that should follow.
* The sandbox is process isolation with timeouts, not a security boundary.

## AI assistance

The benchmark (tasks, tests, reference solutions, vibe prompts), the harness, the analysis, the demos and a
draft of the report were built with an AI coding assistant (Claude Code). All experimental data are real
model generations logged in `results/raw/llm_calls.jsonl`.
