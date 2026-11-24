/* Is Vibecoding a Slot Machine? -- browser demo. No framework, no build step.
   Every value rendered here comes from the local server (results/ or a live model call). */
"use strict";

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x, d = 0) => (x == null ? "n/a" : `${(x * 100).toFixed(d)}%`);
const fmt = (x, d = 2) => (x == null ? "n/a" : Number(x).toFixed(d));
const SPEED = new URLSearchParams(location.search).has("fast") ? 0.15 : 1;
const wait = (ms) => new Promise((r) => setTimeout(r, ms * SPEED));

const OUTCOME_LABEL = { pass: "Pass", near_miss: "Near-miss", fail: "Miss", hidden: "Withheld" };
const TABS = [
  { id: "overview", label: "Overview", key: "O", global: true },
  { id: "pull", label: "Pull", key: "R" },
  { id: "paste", label: "Paste error", key: "E" },
  { sep: true },
  { id: "retry_budget", label: "P1 Budget", key: "1" },
  { id: "hidden_best_of_n", label: "P2 Best-of-5", key: "2" },
  { id: "test_gated_reveal", label: "P3 Gated", key: "3" },
  { id: "typed_holes_patch", label: "P4 Holes", key: "4" },
  { sep: true },
  { id: "compare", label: "Compare", key: "C", global: true },
];
const PATCHES = {
  retry_budget: {
    title: "Patch 1: retry budget + decomposition handoff",
    lede: "The agent gets k automatic attempts. When the budget runs out it stops re-rolling and hands over a skeleton whose open decisions are typed holes for the programmer.",
  },
  hidden_best_of_n: {
    title: "Patch 2: hidden best-of-5 + behavioural diff",
    lede: "Five candidates are generated and tested privately. The programmer sees one result and a summary of where the hidden candidates disagreed, never the near-misses themselves.",
  },
  test_gated_reveal: {
    title: "Patch 3: test-gated reveal + code-free diagnosis",
    lede: "Code is shown only once it passes the programmer's tests. A failing attempt is withheld and replaced by a one-sentence diagnosis of the spec, which the programmer can accept as a clarification.",
  },
  typed_holes_patch: {
    title: "Patch 4: spec-first typed holes",
    lede: "The agent writes the API, boilerplate and executable invariants. The design decisions are left as typed holes that the programmer fills, so the programmer owns the hard lines.",
  },
};

const S = {
  boot: null, tasks: [], byId: new Map(), task: null, data: new Map(),
  tab: "overview", source: "replay", busy: false, runId: 0, peek: false, specOpen: false,
  feedback: "complete", pasteWho: "slot_machine", p4Variant: "typed_holes_patch",
  meter: new Map(), counters: new Map(), last: new Map(), paletteSel: 0,
};

// ------------------------------------------------------------------------------- data
async function api(path, body) {
  const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const json = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
  if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
  return json;
}
async function taskData(id) {
  if (!S.data.has(id)) S.data.set(id, await api(`/api/task/${encodeURIComponent(id)}`));
  return S.data.get(id);
}
const key = (...p) => p.join("|");
const REAL = () => S.feedback === "realistic";
const nVis = () => (S.boot && S.boot.phase3 && S.boot.phase3.n_visible) || 3;
function classify(nPass, nTotal) {
  if (nTotal > 0 && nPass === nTotal) return "pass";
  if (nTotal > 0 && nPass > 0 && (nPass / nTotal >= 0.8 || nTotal - nPass === 1)) return "near_miss";
  return "fail";
}
const REAL_TEXT = {
  paste: {
    title: "Baseline under realistic feedback",
    lede: "The programmer only has their own 3 tests. The vibecoder pastes whatever those tests report and stops when they pass. The attentive programmer reads every attempt and says what to change: the upper bound.",
  },
  retry_budget: { title: "Patch 1 under realistic feedback (k = 1)", lede: "One automatic attempt. The handoff only fires if the programmer's own tests fail, so it cannot catch what those tests do not check." },
  hidden_best_of_n: { title: "Patch 2 under realistic feedback", lede: "Five hidden candidates, ranked by the programmer's own tests. Candidates that pass those tests look identical, so the best one can still be wrong." },
  test_gated_reveal: { title: "Patch 3 under realistic feedback", lede: "Code is revealed once it passes the programmer's tests. When it fails, the programmer checks the diagnosis against what they meant and corrects it if needed." },
  typed_holes_patch: { title: "Patch 4 under realistic feedback", lede: "The programmer fills the holes with what they actually mean. With hole requests, they can also ask for a decision buried in the boilerplate to become a hole, and the agent re-scaffolds once." },
};
const bump = (k) => { const n = S.counters.get(k) || 0; S.counters.set(k, n + 1); return n; };
const meter = () => { const id = S.task.task_id; if (!S.meter.has(id)) S.meter.set(id, []); return S.meter.get(id); };

// ------------------------------------------------------------------------------- code rendering
const KW = new Set("False None True and as assert async await break class continue def del elif else except finally for from global if import in is lambda nonlocal not or pass raise return try while with yield match case".split(" "));
const BI = new Set("self cls len range print int str list dict set tuple sorted min max sum abs enumerate zip map filter isinstance any all reversed super float bool object round divmod iter next hasattr getattr ValueError TypeError KeyError IndexError NotImplementedError Exception RuntimeError ZeroDivisionError".split(" "));
const TOKEN = /(#[^\n]*)|("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|\b(\d+(?:\.\d+)?)\b|\b([A-Za-z_]\w*)\b/g;

function highlight(src) {
  let out = "", last = 0, prevWord = "";
  const span = (cls, text) => text.split("\n").map((seg) => (seg ? `<span class="${cls}">${esc(seg)}</span>` : "")).join("\n");
  for (const m of src.matchAll(TOKEN)) {
    out += esc(src.slice(last, m.index));
    if (m[1]) out += span("tk-com", m[1]);
    else if (m[2]) out += span("tk-str", m[2]);
    else if (m[3]) out += span("tk-num", m[3]);
    else {
      const w = m[4];
      if (w.startsWith("hole_")) out += span("tk-hole", w);
      else if (KW.has(w)) out += span("tk-kw", w);
      else if (prevWord === "def" || prevWord === "class") out += span("tk-def", w);
      else if (BI.has(w)) out += span("tk-bi", w);
      else out += esc(w);
      prevWord = w;
    }
    last = m.index + m[0].length;
  }
  out += esc(src.slice(last));
  return out.split("\n");
}

function holeLines(src) {
  const lines = src.split("\n"), marks = new Array(lines.length).fill(false);
  let inHole = false;
  lines.forEach((l, i) => {
    if (/^def hole_/.test(l)) inHole = true;
    else if (inHole && l.trim() && !/^\s/.test(l)) inHole = false;
    marks[i] = inHole;
  });
  return marks;
}

function codeBlock(src, { max = 60, mode = "", flush = false, animate = true } = {}) {
  src = (src || "").replace(/\s+$/, "");
  if (!src) return `<pre class="code${flush ? " flush" : ""}"><span class="more">(no code)</span></pre>`;
  const lines = highlight(src), holes = mode === "skeleton" ? holeLines(src) : [];
  const shown = lines.slice(0, max);
  const body = shown.map((h, i) => {
    const cls = ["ln", animate ? "assemble" : "", holes[i] ? "hole" : "", mode === "fill" ? "fill" : ""].join(" ");
    return `<span class="${cls}" style="--i:${Math.min(i, 70)}">${h || " "}</span>`;
  }).join("");
  const more = lines.length > max ? `<span class="more"># ${lines.length - max} more lines</span>` : "";
  return `<pre class="code${flush ? " flush" : ""}">${body}${more}</pre>`;
}

// ------------------------------------------------------------------------------- shared fragments
function badge(outcome, nPass, nTotal) {
  const n = nTotal ? `<span class="n">${nPass}/${nTotal}</span>` : "";
  return `<span class="badge ${outcome}">${OUTCOME_LABEL[outcome] || outcome}${n}</span>`;
}

function testResults(a) {
  const names = S.task.tests;
  const failed = new Set(a.intent_failed || a.failed_tests || []);
  const allFailed = ((a.intent_n_pass ?? a.n_pass) === 0) && failed.size === 0;
  const byName = new Map((a.tests || []).map((t) => [t.name, t]));
  return names.map((n) => byName.get(n) || { name: n, passed: !allFailed && !failed.has(n), message: "" });
}

function testStrip(a, animate = true) {
  const real = REAL();
  const cells = testResults(a).map((t, i) => {
    const held = real && i >= nVis();
    const veiled = held && !S.peek;
    const cls = veiled ? "veiled" : (t.passed ? "ok" : "bad");
    const tip = veiled ? `${t.name}: held-out test, not visible to the programmer (press P to peek)`
      : `${t.name}: ${t.passed ? "passed" : "failed"}${held ? " (held-out)" : real ? " (your test)" : ""}`;
    return `<div class="test ${cls} ${held ? "held" : real ? "mine" : ""} ${animate ? "assemble" : ""}" style="--i:${i}" data-tip="${esc(tip)}">
      <span class="dot">${veiled ? "?" : t.passed ? "✓" : "×"}</span><span class="nm">${esc(t.name)}</span></div>`;
  }).join("");
  const legend = real ? `<div class="note" style="margin-top:6px">solid: your ${nVis()} tests · dashed: held-out tests that decide whether the code is right${S.peek ? "" : " (press P to peek)"}</div>` : "";
  return `<div class="tests">${cells}</div>${legend}`;
}

function visibleOf(a) {
  const res = testResults(a).slice(0, nVis());
  const n = res.filter((t) => t.passed).length;
  return { outcome: classify(n, res.length), n_pass: n, n_total: res.length };
}

function truthBadge(outcome, nPass, nTotal) {
  return `<span class="peek-inline note">held-out truth: ${badge(outcome, nPass, nTotal)}</span>`;
}

function failMessages(a, limit = 3) {
  const bad = testResults(a).filter((t, i) => !t.passed && t.message && (!REAL() || S.peek || i < nVis()));
  const parts = [];
  if (a.load_error) parts.push(`<div class="failmsg"><div class="h">module failed to load</div><pre>${esc(a.load_error)}</pre></div>`);
  bad.slice(0, limit).forEach((t) => parts.push(`<div class="failmsg"><div class="h">test ${esc(t.name)}</div><pre>${esc(t.message.trim())}</pre></div>`));
  if (bad.length > limit) parts.push(`<div class="note">+ ${bad.length - limit} more failing tests</div>`);
  return parts.length ? `<div class="fails">${parts.join("")}</div>` : "";
}

function skeletonCard(label) {
  const widths = [62, 48, 74, 35, 58, 66, 41, 52];
  return `<div class="card scanning assemble">
    <div class="card-head"><div class="title"><span class="eyebrow">${esc(label)}</span></div><span class="note" data-elapsed>0.0s</span></div>
    <div class="skeleton-lines">${widths.map((w) => `<i style="width:${w}%"></i>`).join("")}</div></div>`;
}

function startElapsed(root) {
  const t0 = performance.now();
  const h = setInterval(() => {
    const el = root.querySelector("[data-elapsed]");
    if (!el) return clearInterval(h);
    el.textContent = `${((performance.now() - t0) / 1000).toFixed(1)}s`;
  }, 100);
  return () => clearInterval(h);
}

function flash(outcome, nPass, nTotal, suffix = "tests") {
  const el = $("#flash");
  const sub = outcome === "pass" ? `all ${nTotal} ${suffix} pass` : outcome === "near_miss" ? `${nPass}/${nTotal} ${suffix}. One more pull?` : `${nPass}/${nTotal} ${suffix}`;
  el.innerHTML = `<div class="glass"><div class="big ${outcome}">${OUTCOME_LABEL[outcome].toUpperCase()}</div><div class="sub">${esc(sub)}</div></div>`;
  el.hidden = false;
  clearTimeout(flash._t);
  flash._t = setTimeout(() => { el.hidden = true; }, 1500 * Math.max(SPEED, 0.4));
}

function sourceToggle() {
  const live = S.boot.mode === "live" && !REAL();
  return `<div class="seg" role="group" aria-label="Source">
    <button data-source="replay" aria-pressed="${S.source === "replay"}">Recorded</button>
    <button data-source="live" aria-pressed="${S.source === "live"}" ${live ? "" : "disabled"} title="${live ? "Real model call" : REAL() ? "Live runs use complete feedback" : "Restart the server with --live"}">Live</button>
  </div>`;
}

// ------------------------------------------------------------------------------- layout: header, index, tabs
function renderTotals() {
  const t = S.boot.totals;
  $("#totals").textContent = `${(t.models || []).join(", ")} · ${t.calls.toLocaleString()} logged calls · $${t.cost_usd.toFixed(2)}`;
  const pill = $("#mode-pill");
  pill.className = `mode-pill ${S.boot.mode}`;
  pill.querySelector("span").textContent = S.boot.mode === "live" ? "live + replay" : "replay · offline";
}

function renderTaskList() {
  const groups = { humaneval: "HumanEval-adapted", mbpp: "MBPP-style", original: "Original, stateful" };
  let html = "";
  for (const [suite, label] of Object.entries(groups)) {
    html += `<div class="suite-label">${label}</div>`;
    S.tasks.filter((t) => t.suite === suite).forEach((t) => {
      html += `<button class="task-row ${S.task && S.task.task_id === t.task_id ? "active" : ""}" data-task="${t.task_id}">
        <span class="tid">${esc(t.task_id)}${t.suggested ? '<span class="star" title="behaves most like a slot machine">*</span>' : ""}</span>
        <span class="pct">${pct(t.p_pass)}</span>
        <span class="reel">${t.blind_outcomes.map((o) => `<i class="${o}"></i>`).join("")}</span>
      </button>`;
    });
  }
  $("#task-list").innerHTML = html;
  $("#task-count").textContent = `${S.tasks.length} tasks`;
}

function renderTabs() {
  $("#tabs").innerHTML = TABS.map((t) => t.sep ? `<span class="tab-group-sep"></span>` :
    `<button class="tab" role="tab" data-tab="${t.id}" aria-selected="${S.tab === t.id}">${esc(t.label)}<kbd>${t.key}</kbd></button>`).join("");
}

function renderTaskHead() {
  const head = $("#task-head");
  const tab = TABS.find((t) => t.id === S.tab);
  if (tab && tab.global) { head.innerHTML = ""; head.hidden = true; return; }
  head.hidden = false;
  const t = S.task, idx = S.tasks.indexOf(t) + 1;
  head.innerHTML = `
    <div class="eyebrow-row assemble"><span class="eyebrow">Task ${String(idx).padStart(2, "0")} / ${S.tasks.length}</span>
      <span class="chip">${esc(t.suite)}</span>${t.suggested ? '<span class="chip">* slot-machine-like in recorded runs</span>' : ""}</div>
    <h1 class="assemble" style="--i:1">${esc(t.title)}<span class="mono">${esc(t.task_id)}</span></h1>
    <div class="prompt-block assemble" style="--i:2"><div class="k"><span class="eyebrow">What the programmer typed</span></div><div class="v">${esc(t.vibe_prompt)}</div></div>
    ${S.specOpen ? `<div class="prompt-block spec assemble"><div class="k"><span class="eyebrow">What they meant (full spec)</span></div><div class="v">${esc(t.spec_prompt)}</div></div>` : ""}
    <div class="chips assemble" style="--i:3">
      <span class="chip" style="color:var(--z900)">${REAL() ? `${nVis()} your tests + ${t.tests.length - nVis()} held-out` : `${t.tests.length} hidden tests`}</span>
      ${t.tests.map((n, i) => `<span class="chip ${REAL() ? (i < nVis() ? "mine" : "held") : ""}">${esc(n)}</span>`).join("")}
      <button class="linklike" data-action="spec" style="margin-left:6px">${S.specOpen ? "hide full spec" : "show full spec"}</button>
    </div>`;
}

// ------------------------------------------------------------------------------- variance meter
function renderMeter() {
  const pulls = S.task ? meter() : [];
  const n = pulls.length, k = pulls.filter((p) => p.outcome === "pass").length;
  const nm = pulls.filter((p) => p.outcome === "near_miss").length;
  const p = n ? k / n : 0;
  const H = n && p > 0 && p < 1 ? -(p * Math.log2(p) + (1 - p) * Math.log2(1 - p)) : 0;
  let streak = 0;
  for (let i = n - 1; i >= 0 && pulls[i].outcome !== "pass"; i--) streak++;
  const distinct = new Set(pulls.map((x) => (x.failed_tests || []).slice().sort().join(","))).size;
  const on = Math.round(H * 24);
  const t = S.task;
  const reroll = S.boot.phase1.blind_curve ? S.boot.phase1.blind_curve.hazard[1] : null;
  let diag, hot = false;
  if (!n) diag = t ? `Recorded for this task: ${t.blind_outcomes.length} pulls, ${pct(t.p_pass)} pass, H = ${fmt(t.entropy)} bits. Pull the lever to sample it yourself.` : "";
  else if (pulls[n - 1].outcome === "near_miss") {
    hot = true;
    diag = `Near-miss. One more pull feels like it will win.${reroll != null ? ` In the recorded data a blind re-roll after a miss passes only ${pct(reroll)} of the time.` : ""}`;
  } else if (p > 0 && p < 1) diag = "Intermittent payout: a variable-ratio schedule, the reinforcement schedule most resistant to extinction.";
  else if (p === 1 && REAL()) diag = "Every pull passes your tests. Whether it is right is decided by tests you never see: press P to peek.";
  else if (p === 1) diag = "Every pull has paid out so far. Most tasks look like this: 18 of 30 always pass.";
  else diag = "No payout yet. Tasks that never pass in 10 pulls are deterministic failures, not lotteries.";

  const history = Array.from({ length: 30 }, (_, i) => {
    const x = pulls[Math.max(0, n - 30) + i];
    return `<i class="${x ? x.outcome : ""}" ${x ? `data-tip="${OUTCOME_LABEL[x.outcome]} ${x.n_pass}/${x.n_total}"` : ""}></i>`;
  }).join("");
  $("#meter").innerHTML = `
    <div class="card panel">
      <div class="panel-head"><span class="eyebrow">Variance meter</span>
        <button class="linklike" data-action="reset-meter">reset</button></div>
      <div class="rows">
        <div class="row"><span class="k">pulls on this task</span><span class="v">${n}</span></div>
        <div class="row"><span class="k">hit rate</span><span class="v">${n ? pct(p) : "n/a"}</span></div>
        <div class="row" style="display:block"><div style="display:flex;justify-content:space-between"><span class="k">outcome entropy H</span><span class="v">${fmt(H)} <small>bits</small></span></div>
          <div class="hbar">${Array.from({ length: 24 }, (_, i) => `<i class="${i < on ? "on" : ""}"></i>`).join("")}</div></div>
        <div class="row"><span class="k">near-misses</span><span class="v">${nm} <small>${n - k ? `${pct(nm / (n - k))} of misses` : ""}</small></span></div>
        <div class="row"><span class="k">losing streak</span><span class="v">${streak}</span></div>
        <div class="row"><span class="k">distinct test behaviours</span><span class="v">${n ? distinct : "n/a"}</span></div>
      </div>
      <div class="history">${history}</div>
      ${diag ? `<div class="diagnostic ${hot ? "hot" : ""}">${esc(diag)}</div>` : ""}
    </div>`;
}

function renderKeys() {
  const rows = [["R", "pull the lever"], ["E", "paste-the-error loop"], ["1 to 4", "run a patch"], ["P", "peek behind the glass"],
    ["O / C", "overview / compare"], ["F", "all tests / your 3 tests"], ["T", "switch task"], ["[ / ]", "previous / next task"]];
  $("#keys").innerHTML = `<div class="eyebrow" style="margin:0 2px 6px">Keys</div>` +
    rows.map(([k, v]) => `<div class="row"><span>${v}</span><kbd>${k}</kbd></div>`).join("");
}

// ------------------------------------------------------------------------------- stage: overview
function hazardChart() {
  const bc = S.boot.phase1.blind_curve, ec = S.boot.phase1.error_paste_curve;
  if (!bc || !ec) return `<div class="empty">No Phase 1 summary in results/.</div>`;
  const W = 520, H = 280, L = 44, R = 116, T = 16, B = 36;
  const n = bc.hazard.length;
  const x = (i) => L + (i * (W - L - R)) / (n - 1);
  const y = (v) => T + (1 - v) * (H - T - B);
  const grid = [0, 0.25, 0.5, 0.75, 1].map((v) => `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 8}" y="${y(v) + 3}" text-anchor="end">${v * 100}%</text>`).join("");
  const xt = bc.hazard.map((_, i) => `<text x="${x(i)}" y="${H - B + 18}" text-anchor="middle">${i + 1}</text>`).join("");
  const band = (lo, hi, idx) => {
    if (!lo || !hi) return "";
    const pts = idx.filter((i) => lo[i] != null && hi[i] != null);
    if (pts.length < 2) return "";
    return pts.map((i) => `${x(i)},${y(hi[i])}`).join(" ") + " " + pts.slice().reverse().map((i) => `${x(i)},${y(lo[i])}`).join(" ");
  };
  const all = bc.hazard.map((_, i) => i);
  const epIdx = all.filter((i) => ec.hazard[i] != null && (ec.reached ? ec.reached[i] > 0 : true));
  const path = (h, idx) => idx.map((i, j) => `${j ? "L" : "M"}${x(i)},${y(h[i])}`).join(" ");
  const dots = (h, idx, cls, name, extra) => idx.map((i) =>
    `<circle cx="${x(i)}" cy="${y(h[i])}" r="4.5" fill="#fff" stroke-width="2" class="${cls}" data-tip="${name}, attempt ${i + 1}: ${pct(h[i])} pass${extra(i)}"/>`).join("");
  const reach = (i) => (bc.reach ? ` (reached by ${pct(bc.reach[i])} of chains)` : "");
  const epN = (i) => (ec.reached ? ` (n = ${ec.reached[i]} chains)` : "");
  const lb = bc.hazard.length - 1, le = epIdx[epIdx.length - 1];
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Probability that attempt t passes given earlier attempts failed">
    <g class="grid">${grid}</g>
    <line class="axis" x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}"/>
    ${xt}<text x="${(L + W - R) / 2}" y="${H - 4}" text-anchor="middle">attempt t</text>
    <polygon points="${band(bc.hazard_ci_lo, bc.hazard_ci_hi, all)}" fill="rgba(42,120,214,0.10)"/>
    <polygon points="${band(ec.hazard_ci_lo, ec.hazard_ci_hi, epIdx)}" fill="rgba(235,104,52,0.10)"/>
    <path d="${path(bc.hazard, all)}" fill="none" stroke-width="2" class="s-blind"/>
    <path d="${path(ec.hazard, epIdx)}" fill="none" stroke-width="2" class="s-ep"/>
    ${dots(bc.hazard, all, "s-blind", "Blind re-roll", reach)}
    ${dots(ec.hazard, epIdx, "s-ep", "Error-paste", epN)}
    <text class="lbl" x="${x(lb) + 10}" y="${y(bc.hazard[lb]) + 4}">blind re-roll</text>
    <text class="lbl" x="${x(le) + 10}" y="${y(ec.hazard[le]) + 4}">error-paste</text>
  </svg>`;
}

function renderOverview() {
  const p1 = S.boot.phase1, sp = S.boot.spec;
  const counts = p1.outcome_counts || {};
  const tiles = [
    [pct(p1.pass_rate), "of blind pulls pass", `${counts.pass} / ${p1.n_blind_attempts} pulls`],
    [pct(p1.p_nm_given_failure), "of failures are near-misses", "at least 80% of tests, or one test off"],
    [pct(p1.median_frac_tests_passed_in_failures), "of tests pass in the median failure", "so close it invites another pull"],
    [fmt(p1.mean_distinct_behaviours_per_task), "distinct behaviours per task", `in 10 pulls; code ${pct(p1.mean_pairwise_code_similarity_blind)} similar`],
    [sp.n ? `${Math.round(sp.pass_rate * sp.n)}/${sp.n}` : "n/a", "pass with the full spec", `entropy ${fmt(sp.mean_entropy_bits)} bits`],
  ];
  const rows = S.tasks.slice().sort((a, b) => (b.entropy - a.entropy) || (a.p_pass - b.p_pass));
  const tr = p1.error_paste_transitions || {};
  $("#stage").innerHTML = `
    <p class="lede assemble">Phase 1 measured ${p1.n_tasks} tasks with ${p1.n_blind_attempts} blind pulls of a terse "vibe" prompt. The hidden tests encode what the programmer meant.</p>
    <div class="tiles">${tiles.map(([v, k, s], i) => `<div class="tile assemble" style="--i:${i}"><div class="v" data-count>${esc(v)}</div><div class="k">${esc(k)}</div><div class="s">${esc(s)}</div></div>`).join("")}</div>
    <div class="two-col">
      <div class="card assemble" style="--i:5">
        <div class="card-head"><div class="title">Should you pull again?</div><span class="note">P(pass at t | earlier attempts failed)</span></div>
        <div class="legend" style="padding-top:12px"><span><i style="background:var(--pass)"></i>blind re-roll</span><span><i style="background:var(--nm)"></i>paste the error back</span><span class="note">bands: 95% CI</span></div>
        <div style="padding:0 6px 8px">${hazardChart()}</div>
        <div class="card-body" style="border-top:1px solid var(--line)"><div class="note">Blind re-rolls stop paying quickly. Pasting the failure back passes ${pct(tr.p_pass_after_near_miss)} of the time after a near-miss, because the test output carries the intent the prompt left out.</div></div>
      </div>
      <div class="card assemble" style="--i:6">
        <div class="card-head"><div class="title">${p1.n_blind_attempts} recorded pulls</div><span class="note">sorted by entropy H</span></div>
        <div class="card-body"><div class="matrix">
          ${rows.map((t, i) => `<span class="rowname assemble" style="--i:${Math.min(i, 30)}" data-open="${t.task_id}">${esc(t.task_id)}</span>
            <span class="cells">${t.blind_outcomes.map((o, j) => `<i class="${o}" data-tip="${esc(t.task_id)} pull ${j + 1}: ${OUTCOME_LABEL[o]}"></i>`).join("")}</span>
            <span class="h">${fmt(t.entropy)}</span>`).join("")}
        </div></div>
      </div>
    </div>`;
}

// ------------------------------------------------------------------------------- stage: compare
function renderCompareRealistic() {
  const p3 = S.boot.phase3 || {}, W = p3.variants || {};
  const names = (p3.order || []).filter((n) => W[n]);
  if (!names.length) { $("#stage").innerHTML = `<div class="empty">No Phase 3 summary in results/. Run python -m analysis.phase3.</div>`; return; }
  const bar = (v, cls, text) => `<span class="bar-cell ${cls}">${text}<i style="width:${Math.max(1, Math.round(56 * (v || 0)))}px"></i></span>`;
  const tabFor = (n) => (n === "slot_machine" || n === "attentive" ? "paste" : n === "typed_holes_fixed" ? "typed_holes_patch" : n);
  const signed = (x) => { const v = Math.round(100 * x); return v === 0 ? "0" : `${v > 0 ? "+" : "−"}${Math.abs(v)}`; };
  const delta = (d) => (d && d.delta != null ? `${signed(d.delta)} <span style="color:var(--z400)">[${Math.round(100 * d.lo)}, ${Math.round(100 * d.hi)}]</span>` : "--");
  $("#stage").innerHTML = `
    <p class="lede assemble">Realistic feedback: everyone sees only the programmer's own ${p3.n_visible || 3} tests per task; held-out tests decide whether the final code is right. The simulated programmer knows what they meant. "Silent failure" means the code passed the programmer's tests and was still wrong.</p>
    <div class="table-wrap assemble" style="--i:1"><table class="cmp">
      <thead><tr><th>condition</th><th>intent pass</th><th>silent failure</th><th>vs vibecoder, pts [95% CI]</th><th>near-misses shown</th><th>your decisions</th><th>your turns</th><th>agent tokens</th></tr></thead>
      <tbody>${names.map((n, i) => {
        const v = W[n];
        return `<tr class="${n === "slot_machine" ? "base" : ""} assemble" style="--i:${i + 2};cursor:pointer" data-goto="${tabFor(n)}" data-variant="${n}">
          <td>${esc((p3.labels || {})[n] || n)}</td>
          <td>${bar(v.intent_pass_rate, "dec", pct(v.intent_pass_rate))}</td>
          <td>${bar(v.silent_failure_rate, "nm", pct(v.silent_failure_rate))}</td>
          <td>${n === "slot_machine" ? "--" : delta(v.delta_intent_vs_vibecoder)}</td>
          <td>${fmt(v.visible_near_misses_per_session)}</td>
          <td>${fmt(v.decision_points_per_session)}</td>
          <td>${fmt(v.human_turns_per_session)}</td>
          <td>${(v.agent_tokens_per_session / 1000).toFixed(1)}k <span style="color:var(--z400)">${v.token_ratio_vs_vibecoder != null ? v.token_ratio_vs_vibecoder.toFixed(1) + "×" : ""}</span></td>
        </tr>`;
      }).join("")}</tbody></table></div>
    <p class="note assemble" style="--i:10;margin-top:12px">Intervals resample tasks (paired with the vibecoder baseline). Press F to switch back to complete test feedback.</p>`;
}

function renderCompare() {
  if (REAL()) return renderCompareRealistic();
  const p2 = S.boot.phase2, V = p2.variants;
  const names = ["slot_machine", "retry_budget", "retry_budget_k1", "retry_budget_k2", "hidden_best_of_n", "test_gated_reveal", "typed_holes_patch"].filter((n) => V[n]);
  if (!names.length) { $("#stage").innerHTML = `<div class="empty">No Phase 2 summary in results/.</div>`; return; }
  const max = (f) => Math.max(...names.map((n) => V[n][f] || 0)) || 1;
  const mNM = max("visible_near_misses_per_session"), mDec = max("decision_points_per_session"), mTok = max("agent_tokens_per_session");
  const base = V.slot_machine ? V.slot_machine.agent_tokens_per_session : null;
  const bar = (v, m, cls, text) => `<span class="bar-cell ${cls}">${text}<i style="width:${Math.max(1, Math.round(56 * (v || 0) / m))}px"></i></span>`;
  const tabFor = (n) => (n.startsWith("retry_budget") ? "retry_budget" : n === "slot_machine" ? "paste" : n);
  $("#stage").innerHTML = `
    <p class="lede assemble">All 30 tasks, ${S.boot.phase2.variants.slot_machine ? S.boot.phase2.variants.slot_machine.n_sessions / 30 : 10} sessions per task (P4: 5). "Visible" counts only what the programmer is shown. Human work in P1 handoffs and P4 is done by a simulated programmer.</p>
    <div class="table-wrap assemble" style="--i:1"><table class="cmp">
      <thead><tr><th>condition</th><th>pass</th><th>visible H</th><th>near-misses shown</th><th>passive retries</th><th>your decisions</th><th>your lines</th><th>agent calls</th><th>agent tokens</th></tr></thead>
      <tbody>${names.map((n, i) => {
        const v = V[n];
        return `<tr class="${n === "slot_machine" ? "base" : ""} assemble" style="--i:${i + 2};cursor:pointer" data-goto="${tabFor(n)}">
          <td>${esc(p2.labels[n] || n)}</td>
          <td>${pct(v.final_pass_rate)}</td>
          <td>${fmt(v.visible_entropy_bits)}</td>
          <td>${bar(v.visible_near_misses_per_session, mNM, "nm", fmt(v.visible_near_misses_per_session))}</td>
          <td>${fmt(v.passive_retries_per_session)}</td>
          <td>${bar(v.decision_points_per_session, mDec, "dec", fmt(v.decision_points_per_session))}</td>
          <td>${pct(v.human_line_frac)}</td>
          <td>${fmt(v.agent_calls_per_session, 1)}</td>
          <td>${bar(v.agent_tokens_per_session, mTok, "tok", `${(v.agent_tokens_per_session / 1000).toFixed(1)}k${base ? ` <span style="color:var(--z400)">${(v.agent_tokens_per_session / base).toFixed(1)}×</span>` : ""}`)}</td>
        </tr>`;
      }).join("")}</tbody></table></div>
    <p class="note assemble" style="--i:10;margin-top:12px">Per session averages. Click a row to replay that condition on the current task (${esc(S.task.task_id)}).</p>`;
}

// ------------------------------------------------------------------------------- stage: pull
function pullResultCard(a, meta, animate = true) {
  let head = badge(a.outcome, a.n_pass, a.n_total);
  if (REAL()) {
    const v = visibleOf(a);
    head = `<span class="eyebrow">your tests</span>${badge(v.outcome, v.n_pass, v.n_total)}${truthBadge(a.outcome, a.n_pass, a.n_total)}`;
  }
  return `<div class="card ${animate ? "assemble" : ""}">
      <div class="card-head"><div class="result-head">${head}<span class="meta">${esc(meta)}</span></div></div>
      <div class="card-body stack">${testStrip(a, animate)}${failMessages(a)}</div>
      ${codeBlock(a.code, { max: 80, animate })}
    </div>`;
}

function renderPull() {
  const last = S.last.get(key("pull", S.task.task_id));
  const n = S.counters.get(key("pull", S.task.task_id)) || 0;
  $("#stage").innerHTML = `
    <div class="toolbar">
      <button class="btn" data-run="pull" ${S.busy ? "disabled" : ""}>Pull the lever <kbd>R</kbd></button>
      ${sourceToggle()}
      <span class="spacer"></span>
      <span class="note">${REAL() ? "Realistic: you only see your first " + nVis() + " tests. " : ""}${n ? `${n} pull${n > 1 ? "s" : ""} this session` : "Same prompt every time. Only the sample changes."}</span>
    </div>
    <div id="pull-out" class="pull-grid">${last ? pullResultCard(last.a, last.meta, false) :
      `<div class="empty"><div class="big">One prompt, many outcomes</div>Each pull sends the identical prompt again. Recorded pulls cycle through the ${S.task.blind_outcomes.length} logged generations for this task.</div>`}</div>`;
}

async function runPull() {
  if (S.busy) return;
  setTab("pull", false);
  const id = ++S.runId, task = S.task, mt = meter();
  const n = bump(key("pull", task.task_id));
  S.busy = true; renderPull();
  const out = $("#pull-out");
  out.innerHTML = skeletonCard(S.source === "live" ? "generating (live model call)" : "pulling the lever: replaying a logged call");
  const stop = startElapsed(out);
  try {
    let a, meta;
    if (S.source === "live") {
      a = await api("/api/live/pull", { task_id: task.task_id });
      meta = `pull ${n + 1} · live`;
    } else {
      const d = await taskData(task.task_id);
      if (!d.blind.length) throw new Error("No recorded pulls for this task.");
      a = d.blind[n % d.blind.length];
      meta = `pull ${n + 1} · logged generation ${a.chain + 1} of ${d.blind.length}`;
      await wait(850);
    }
    S.last.set(key("pull", task.task_id), { a, meta });
    if (REAL()) {
      const v = visibleOf(a);
      mt.push({ ...v, failed_tests: testResults(a).slice(0, nVis()).filter((t) => !t.passed).map((t) => t.name) });
    } else mt.push(a);
    if (id !== S.runId) return;
    out.innerHTML = pullResultCard(a, meta);
    renderMeter();
    await wait(Math.min(900, 60 * task.tests.length + 200));
    if (id === S.runId) {
      if (REAL()) { const v = visibleOf(a); flash(v.outcome, v.n_pass, v.n_total, "of your tests"); }
      else flash(a.outcome, a.n_pass, a.n_total);
    }
  } catch (e) {
    if (id === S.runId) out.innerHTML = errorCard(e);
  } finally {
    stop(); S.busy = false;
    if (id === S.runId) { const b = $("[data-run=pull]"); if (b) b.disabled = false; }
  }
}

function errorCard(e) {
  return `<div class="empty"><div class="big">That did not work</div><span class="mono">${esc(e.message || e)}</span></div>`;
}

// ------------------------------------------------------------------------------- stage: error-paste
function turnItem(a, i, prev, animate) {
  const firstFail = prev ? testResults(prev).find((t) => !t.passed && t.message) : null;
  const courier = prev ? `<div class="courier ${animate ? "assemble" : ""}">programmer pastes the pytest output (${prev.n_total - prev.n_pass} failing): "Please fix it."</div>
     ${firstFail ? `<div class="failmsg ${animate ? "assemble" : ""}" style="margin-top:6px"><div class="h">pasted: test ${esc(firstFail.name)}</div><pre>${esc(firstFail.message.trim())}</pre></div>` : ""}` : "";
  return `<div class="tl-item">
    <div class="tl-rail"><div class="tl-node ${a.outcome}">${i + 1}</div><div class="tl-line"></div></div>
    <div class="tl-body stack">
      ${courier}
      <div class="card ${animate ? "assemble" : ""}">
        <div class="card-head"><div class="result-head"><span class="eyebrow">Turn ${i + 1} · ${i ? "after paste" : "generate"}</span>${badge(a.outcome, a.n_pass, a.n_total)}</div></div>
        <div class="card-body">${testStrip(a, animate)}</div>
        <details ${a.outcome === "pass" ? "open" : ""} style="border-top:1px solid var(--line)"><summary class="note" style="padding:8px 14px;cursor:pointer">code</summary>${codeBlock(a.code, { max: 60, animate })}</details>
      </div>
    </div></div>`;
}

function renderPaste() {
  if (REAL()) return renderPatch("paste");
  const last = S.last.get(key("paste", S.task.task_id));
  $("#stage").innerHTML = `
    <div class="toolbar">
      <button class="btn" data-run="paste" ${S.busy ? "disabled" : ""}>Paste the error <kbd>E</kbd></button>
      ${sourceToggle()}<span class="spacer"></span>
      <span class="note">The baseline workflow: generate, paste the failing tests back, repeat.</span>
    </div>
    <div id="paste-out">${last ? pasteBody(last.turns, last.meta, false) :
      `<div class="empty"><div class="big">The programmer as courier</div>Replays a logged error-paste chain, starting with chains whose first attempt failed.</div>`}</div>`;
}

function pasteBody(turns, meta, animate, upto = turns.length) {
  const items = turns.slice(0, upto).map((a, i) => turnItem(a, i, i ? turns[i - 1] : null, animate)).join("");
  const done = upto >= turns.length;
  return `<p class="note" style="margin:0 0 10px">${esc(meta)}</p><div class="timeline">${items}</div>
    ${done ? `<div class="diagnostic assemble" style="margin:4px 0 0 40px">The programmer carried text between the test runner and the model: 0 decisions made, 0 lines written.</div>` : ""}`;
}

async function runPaste() {
  if (REAL()) return runPatch("paste");
  if (S.busy) return;
  setTab("paste", false);
  const id = ++S.runId, task = S.task, mt = meter();
  S.busy = true; renderPaste();
  const out = $("#paste-out");
  out.innerHTML = skeletonCard(S.source === "live" ? "running a live error-paste session" : "loading a logged chain");
  const stop = startElapsed(out);
  let turns = [], shown = 0;
  try {
    let meta;
    const n = bump(key("paste", task.task_id));
    if (S.source === "live") {
      turns = await api("/api/live/error_paste", { task_id: task.task_id });
      meta = "live session";
    } else {
      const d = await taskData(task.task_id);
      if (!d.error_paste.length) throw new Error("No recorded chains for this task.");
      turns = d.error_paste[n % d.error_paste.length];
      meta = `logged chain ${turns[0].chain + 1} · ${turns.length} turn${turns.length > 1 ? "s" : ""}`;
      await wait(500);
    }
    S.last.set(key("paste", task.task_id), { turns, meta });
    for (shown = 1; shown <= turns.length; shown++) {
      if (id !== S.runId) break;
      out.innerHTML = pasteBody(turns, meta, true, shown);
      // keep earlier turns static so only the newest one assembles
      out.querySelectorAll(".tl-item").forEach((el, i) => { if (i < shown - 1) el.querySelectorAll(".assemble").forEach((x) => x.classList.remove("assemble")); });
      mt.push(turns[shown - 1]); renderMeter();
      await wait(1100);
    }
  } catch (e) {
    if (id === S.runId) out.innerHTML = errorCard(e);
  } finally {
    // a run interrupted by a task/tab switch still records its remaining turns on its own task
    for (let i = Math.max(shown, 1); i <= turns.length; i++) mt.push(turns[i - 1]);
    stop(); S.busy = false;
    if (id === S.runId) { renderMeter(); const b = $("[data-run=paste]"); if (b) b.disabled = false; }
  }
}

// ------------------------------------------------------------------------------- stage: patches
function evBadge(e) {
  const b = badge(e.outcome, e.n_pass, e.n_total);
  if (e.intent_outcome == null) return b;
  return `<span class="eyebrow">your tests</span>${b}${truthBadge(e.intent_outcome, e.intent_n_pass, e.intent_n_total)}`;
}

function eventHtml(e, s, i, animate) {
  const A = animate ? "assemble" : "";
  const node = (label, outcome = "") => `<div class="tl-rail"><div class="tl-node ${outcome}">${label}</div><div class="tl-line"></div></div>`;
  const wrap = (label, outcome, body) => `<div class="tl-item">${node(label, outcome)}<div class="tl-body">${body}</div></div>`;
  switch (e.kind) {
    case "code":
      return wrap(i + 1, e.outcome, `<div class="card ${A}"><div class="card-head"><div class="result-head"><span class="eyebrow">${e.note ? "Skeleton came back complete" : `Attempt ${e.turn || ""} · shown to you`}</span>${evBadge(e)}</div></div>
        <div class="card-body">${testStrip(e, animate)}</div></div>`);
    case "best_of_n": {
      const hidden = e.hidden_outcomes || [];
      const m = /Surfaced candidate (\d+)/.exec(e.diff || "");
      const surfaced = m ? Number(m[1]) - 1 : -1;
      const tiles = hidden.map((o, j) => `<div class="candidate glass ${j === surfaced ? "surfaced" : ""} ${A}" style="--i:${j}">
          <div class="ghost-code">${[70, 52, 84, 40, 66, 58].map((w) => `<i style="width:${w}%"></i>`).join("")}</div>
          <div class="label"><span><b>candidate ${j + 1}</b><br>${j === surfaced ? "surfaced to you" : "hidden"}</span>
            <span class="peek">${badge(o)}</span></div></div>`).join("");
      return wrap(`R${e.round || 1}`, e.outcome, `<div class="stack">
        <div class="eyebrow ${A}">Round ${e.round || 1}: ${hidden.length} candidates generated and tested privately</div>
        <div class="hidden-row">${tiles}</div>
        <div class="card ${A}"><div class="card-head"><div class="title">Behavioural diff of hidden candidates</div><span class="tag ok">no code</span></div>
          <div class="card-body"><pre class="diff">${esc(e.diff || "")}</pre></div></div>
        <div class="card ${A}"><div class="card-head"><div class="result-head"><span class="eyebrow">What you see</span>${evBadge(e)}</div></div>
          <div class="card-body">${testStrip(e, animate)}</div></div></div>`);
    }
    case "hidden_attempt":
      return wrap(e.turn || i + 1, "", `<div class="withheld glass ${A}">
        <div class="ghost-code">${[64, 48, 80, 36, 72, 55, 44].map((w) => `<i style="width:${w}%"></i>`).join("")}</div>
        <div class="over"><span class="t">Attempt ${e.turn || ""} withheld</span>
          <span class="s">It does not pass your tests. No score, no almost-working code to tweak.</span>
          <span class="peek s">behind the glass: ${badge(e.true_outcome || "fail", e.n_pass, e.n_total)}</span></div></div>`);
    case "diagnosis": {
      const text = String(e.text || "").trim().replace(/^"(.*)"$/s, "$1");
      return wrap("?", "", `<div class="card diag ${A}"><div class="card-head"><div class="title">Diagnosis, no code: add this to your spec?</div>
          <span class="tag ${e.code_free ? "ok" : "warn"}">${e.code_free ? "code-free" : "flagged by code check"}</span></div>
        <div class="card-body"><blockquote>${esc(text)}</blockquote></div>
        <div class="card-body note" style="border-top:1px solid var(--line);padding-top:8px;padding-bottom:8px">accepted as a clarification by the simulated programmer</div></div>`);
    }
    case "revealed":
      return wrap("✓", e.outcome, `<div class="card ${A}"><div class="card-head"><div class="result-head"><span class="eyebrow">${REAL() ? "Your tests pass" : "All tests pass"} · code revealed</span>${evBadge(e)}</div></div>
        <div class="card-body">${testStrip(e, animate)}</div>${codeBlock(s.final_code, { max: 60, animate })}</div>`);
    case "scaffold": {
      const handoff = s.condition === "retry_budget";
      const valid = e.invariants_valid_ref, total = e.n_invariants;
      return wrap("S", "", `<div class="card ${A}">
        <div class="card-head"><div class="title">${e.rescaffold ? "Re-scaffolded: your decision is now a hole" : handoff ? "Budget spent: decomposition handoff" : "Spec-first skeleton"}</div><span class="note">${e.skeleton_lines || ""} lines by the agent</span></div>
        <div class="card-body stack">
          <div class="note">The agent wrote the API, the boilerplate and ${total} executable invariants (${valid} of ${total} hold on the reference solution). The open decisions are typed holes:</div>
          <div class="holes">${(e.holes || []).map((h) => `<span class="hole-chip">${esc(h)}</span>`).join("")}</div>
        </div>
        ${s.skeleton && !s.events.slice(i + 1).some((x) => x.kind === "scaffold") ? codeBlock(s.skeleton, { max: 90, mode: "skeleton", animate }) : ""}
        ${(s.invariants || []).length ? `<details style="border-top:1px solid var(--line)"><summary class="note" style="padding:8px 14px;cursor:pointer">${s.invariants.length} invariants</summary>${codeBlock(s.invariants.join("\n"), { max: 40, animate: false })}</details>` : ""}
      </div>`);
    }
    case "human_fill": {
      const fills = s.fills && (i === s.events.length - 1 || !s.events.slice(i + 1).some((x) => x.kind === "human_fill"));
      return wrap(`H${e.round || 1}`, e.outcome, `<div class="card ${A}">
        <div class="card-head"><div class="result-head"><span class="eyebrow">You fill the holes · round ${e.round || 1} · ${e.fill_lines || 0} lines</span>${evBadge(e)}</div><span class="tag">simulated programmer</span></div>
        <div class="card-body stack">${testStrip(e, animate)}${failMessages(e)}</div>
        ${fills ? codeBlock(s.fills, { max: 60, mode: "fill", animate }) : ""}</div>`);
    }
    case "review":
      return wrap("R", "", `<div class="card ${e.accepted ? "" : "diag"} ${A}"><div class="card-head"><div class="title">${e.accepted ? "You read the code: accept" : "You read the code and ask for a change"}</div><span class="tag">simulated programmer</span></div>
        ${e.accepted ? "" : `<div class="card-body"><blockquote class="quote">${esc(e.text || "")}</blockquote></div>`}</div>`);
    case "diagnosis_review":
      return wrap("✎", "", `<div class="card ${A}"><div class="card-head"><div class="title">${e.accepted ? "You check it against what you meant: accepted" : "You correct the diagnosis"}</div><span class="tag ${e.accepted ? "ok" : "warn"}">${e.accepted ? "accepted" : "corrected"}</span></div>
        ${e.accepted ? "" : `<div class="card-body"><blockquote class="quote">${esc(e.text || "")}</blockquote></div>`}</div>`);
    case "hole_request":
      return wrap("+", "", `<div class="card diag ${A}"><div class="card-head"><div class="title">You ask for a buried decision to become a hole</div><span class="tag warn">hole request</span></div>
        <div class="card-body"><blockquote class="quote">${esc(e.text || "")}</blockquote></div></div>`);
    default:
      return wrap(i + 1, e.outcome || "", `<div class="card"><div class="card-body note">${esc(e.kind)}</div></div>`);
  }
}

function shippedCard(s) {
  const lastTruth = [...(s.events || [])].reverse().find((e) => e.intent_n_pass != null);
  let cls = "", title, body;
  if (!s.visible_pass) {
    title = s.final_code ? "Shipped with your tests still failing" : "Nothing shipped";
    body = s.final_code ? "The budget ran out before your tests passed." : "No attempt passed your tests, so no code was revealed.";
    cls = "fail";
  } else if (s.intent_pass) {
    title = "Shipped, and it is right"; cls = "pass";
    body = `Your ${nVis()} tests pass and so do all held-out tests.`;
  } else {
    title = "Shipped. It looks done, and it is wrong"; cls = "silent";
    body = `Your ${nVis()} tests pass, but the held-out tests do not${lastTruth ? ` (${lastTruth.intent_n_pass}/${lastTruth.intent_n_total} overall)` : ""}. A loss disguised as a win.`;
  }
  return `<div class="card shipped ${cls} assemble"><div class="card-head"><div class="title">${title}</div>
    ${lastTruth ? badge(lastTruth.intent_outcome, lastTruth.intent_n_pass, lastTruth.intent_n_total) : ""}</div>
    <div class="card-body note">${esc(body)}</div></div>`;
}

function scorecard(s) {
  if (s.intent_pass != null) {
    const cells = [
      ["intent pass", s.intent_pass ? "yes" : "no"],
      ["silent failure", s.silent_failure ? "yes" : "no"],
      ["outcomes shown", s.n_pulls],
      ["near-misses shown", s.visible_near_misses],
      ["your decisions", s.decision_points],
      ["your turns", s.human_turns],
      ["your lines", `${s.human_lines}<small>/${s.total_lines}</small>`],
      ["agent calls", s.agent_calls],
      ["agent tokens", `${(((s.agent_input_tokens || 0) + (s.agent_output_tokens || 0)) / 1000).toFixed(1)}<small>k</small>`],
    ];
    return `<div class="scorecard assemble">${cells.map(([k, v], i) => `<div class="cell assemble" style="--i:${i}"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("")}</div>`;
  }
  const cells = [
    ["final pass", s.final_pass ? "yes" : "no"],
    ["outcomes shown", s.n_pulls],
    ["near-misses shown", s.visible_near_misses],
    ["passive retries", s.passive_retries],
    ["your decisions", s.decision_points],
    ["your lines", `${s.human_lines}<small>/${s.total_lines}</small>`],
    ["agent calls", s.agent_calls],
    ["agent tokens", `${(((s.agent_input_tokens || 0) + (s.agent_output_tokens || 0)) / 1000).toFixed(1)}<small>k</small>`],
    ["agent time", `${fmt(s.agent_latency_s, 1)}<small>s</small>`],
  ];
  return `<div class="scorecard assemble">${cells.map(([k, v], i) => `<div class="cell assemble" style="--i:${i}"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("")}</div>`;
}

function patchBody(s, meta, animate, upto) {
  const events = s.events || [];
  const n = upto == null ? events.length : upto;
  const items = events.slice(0, n).map((e, i) => eventHtml(e, s, i, animate && i === n - 1)).join("");
  return `<p class="note" style="margin:0 0 10px">${esc(meta)}</p>
    <div class="timeline">${items}</div>
    ${n >= events.length ? `${s.intent_pass != null ? `<div style="margin:8px 0 0 40px">${shippedCard(s)}</div>` : ""}<div class="eyebrow" style="margin:10px 0 8px">Session scorecard</div>${scorecard(s)}` : ""}`;
}

function realisticVariant(cond) {
  if (cond === "paste") return S.pasteWho;
  if (cond === "typed_holes_patch") return S.p4Variant;
  return cond;
}
const slotKey = (cond) => key(cond, REAL() ? `r:${realisticVariant(cond)}` : "c", S.task.task_id);

function variantSeg(cond) {
  if (!REAL()) return "";
  if (cond === "paste") return `<div class="seg" role="group"><button data-who="slot_machine" aria-pressed="${S.pasteWho === "slot_machine"}">Vibecoder</button><button data-who="attentive" aria-pressed="${S.pasteWho === "attentive"}">Attentive</button></div>`;
  if (cond === "typed_holes_patch") return `<div class="seg" role="group"><button data-p4="typed_holes_patch" aria-pressed="${S.p4Variant === "typed_holes_patch"}">P4</button><button data-p4="typed_holes_fixed" aria-pressed="${S.p4Variant === "typed_holes_fixed"}">P4 + hole requests</button></div>`;
  return "";
}

function renderPatch(cond) {
  const P = (REAL() && REAL_TEXT[cond]) || PATCHES[cond];
  const last = S.last.get(slotKey(cond));
  const hasPeek = REAL() || cond === "hidden_best_of_n" || cond === "test_gated_reveal";
  const k = TABS.find((t) => t.id === cond).key;
  $("#stage").innerHTML = `
    <div class="assemble"><div class="eyebrow" style="margin-bottom:4px">${esc(P.title)}</div><p class="lede">${esc(P.lede)}</p></div>
    <div class="toolbar">
      <button class="btn" data-run="${cond}" ${S.busy ? "disabled" : ""}>Run a session <kbd>${k}</kbd></button>
      ${variantSeg(cond)}${sourceToggle()}
      ${hasPeek ? `<button class="btn ghost" data-action="peek" aria-pressed="${S.peek}">${S.peek ? "Hide" : "Peek"} behind the glass <kbd>P</kbd></button>` : ""}
      <span class="spacer"></span>
    </div>
    <div id="patch-out" class="${S.peek ? "peeking" : ""}">${last ? patchBody(last.s, last.meta, false) :
      `<div class="empty"><div class="big">No session yet</div>Recorded sessions where the patch actually intervened are shown first.</div>`}</div>`;
}

async function runPatch(cond) {
  if (S.busy) return;
  setTab(cond, false);
  const id = ++S.runId, task = S.task, slot = slotKey(cond);
  S.busy = true; renderPatch(cond);
  const out = $("#patch-out");
  out.innerHTML = skeletonCard(S.source === "live" ? "running the protocol live (several model calls)" : "loading a logged session");
  const stop = startElapsed(out);
  try {
    let s, meta;
    const n = bump(slot);
    if (S.source === "live" && !REAL()) {
      s = await api("/api/live/patch", { task_id: task.task_id, condition: cond });
      meta = "live session";
    } else {
      const d = await taskData(task.task_id);
      const list = (REAL() ? (d.realistic || {})[realisticVariant(cond)] : d.sessions[cond]) || [];
      if (!list.length) throw new Error(REAL() ? "No realistic-feedback session recorded for this task. Run python -m harness.evaluate_realistic." : "No recorded session for this task and patch.");
      s = list[n % list.length];
      const variant = cond === "retry_budget" ? ` · retry budget k = ${s.k}` : "";
      meta = `${REAL() ? "realistic feedback · " : ""}logged session ${(n % list.length) + 1} of ${list.length}${variant}`;
      await wait(500);
    }
    S.last.set(slot, { s, meta });
    const events = s.events || [];
    for (let shown = 1; shown <= events.length; shown++) {
      if (id !== S.runId) return;
      out.innerHTML = patchBody(s, meta, true, shown);
      if (shown < events.length) await wait(events[shown - 1].kind === "scaffold" ? 1600 : 1150);
    }
  } catch (e) {
    if (id === S.runId) out.innerHTML = errorCard(e);
  } finally {
    stop(); S.busy = false;
    if (id === S.runId) { const b = $(`[data-run="${cond}"]`); if (b) b.disabled = false; }
  }
}

// ------------------------------------------------------------------------------- navigation
function renderStage() {
  $("#stage").classList.toggle("peeking", S.peek);
  if (S.tab === "overview") renderOverview();
  else if (S.tab === "compare") renderCompare();
  else if (S.tab === "pull") renderPull();
  else if (S.tab === "paste") renderPaste();
  else renderPatch(S.tab);
}

function setTab(tab, render = true) {
  if (S.tab !== tab) { S.tab = tab; S.runId++; S.busy = false; }
  renderTabs(); renderTaskHead();
  if (render) renderStage();
  syncHash();
}

function setTask(id) {
  const t = S.byId.get(id);
  if (!t) return;
  if (S.task !== t) { S.task = t; S.runId++; S.busy = false; S.specOpen = false; }
  renderTaskList(); renderTaskHead(); renderMeter(); renderStage(); syncHash();
  $(`.task-row[data-task="${id}"]`)?.scrollIntoView({ block: "nearest" });
  taskData(id).catch(() => {});
}

function syncHash() {
  const h = `#task=${encodeURIComponent(S.task.task_id)}&tab=${S.tab}${REAL() ? "&fb=realistic" : ""}`;
  if (location.hash !== h) history.replaceState(null, "", h);
}

// palette
function openPalette() {
  $("#palette").hidden = false;
  const input = $("#palette-input");
  input.value = ""; S.paletteSel = 0; renderPalette(); input.focus();
}
function closePalette() { $("#palette").hidden = true; }
function paletteMatches() {
  const q = $("#palette-input").value.trim().toLowerCase();
  return S.tasks.filter((t) => !q || `${t.task_id} ${t.title} ${t.vibe_prompt}`.toLowerCase().includes(q));
}
function renderPalette() {
  const m = paletteMatches();
  S.paletteSel = Math.max(0, Math.min(S.paletteSel, m.length - 1));
  $("#palette-list").innerHTML = m.map((t, i) => `<div class="palette-item ${i === S.paletteSel ? "sel" : ""}" data-task="${t.task_id}">
    <span class="tid">${esc(t.task_id)}${t.suggested ? ' <span style="color:var(--nm)">*</span>' : ""}</span><span class="vp">${esc(t.vibe_prompt)}</span></div>`).join("") ||
    `<div class="palette-item"><span class="note">no match</span></div>`;
  $(".palette-item.sel")?.scrollIntoView({ block: "nearest" });
}

// ------------------------------------------------------------------------------- events
function bindEvents() {
  document.addEventListener("click", (ev) => {
    const el = ev.target.closest("[data-task],[data-tab],[data-run],[data-action],[data-source],[data-open],[data-goto],[data-feedback],[data-who],[data-p4]");
    if (!el) { if (ev.target.id === "palette") closePalette(); return; }
    if (el.dataset.task) { closePalette(); setTask(el.dataset.task); }
    else if (el.dataset.tab) setTab(el.dataset.tab);
    else if (el.dataset.open) { setTask(el.dataset.open); setTab("pull"); }
    else if (el.dataset.goto) {
      const v = el.dataset.variant;
      if (v === "slot_machine" || v === "attentive") S.pasteWho = v;
      if (v === "typed_holes_patch" || v === "typed_holes_fixed") S.p4Variant = v;
      setTab(el.dataset.goto);
    }
    else if (el.dataset.run) run(el.dataset.run);
    else if (el.dataset.source) { if (!el.disabled) { S.source = el.dataset.source; renderStage(); } }
    else if (el.dataset.action === "spec") { S.specOpen = !S.specOpen; renderTaskHead(); }
    else if (el.dataset.action === "reset-meter") { S.meter.set(S.task.task_id, []); renderMeter(); }
    else if (el.dataset.action === "peek") togglePeek();
    else if (el.dataset.feedback) setFeedback(el.dataset.feedback);
    else if (el.dataset.who) { S.pasteWho = el.dataset.who; S.runId++; S.busy = false; renderStage(); }
    else if (el.dataset.p4) { S.p4Variant = el.dataset.p4; S.runId++; S.busy = false; renderStage(); }
  });
  $("#open-palette").addEventListener("click", openPalette);
  $("#palette").addEventListener("click", (ev) => { if (ev.target.id === "palette") closePalette(); });
  $("#palette-input").addEventListener("input", () => { S.paletteSel = 0; renderPalette(); });
  $("#palette-input").addEventListener("keydown", (ev) => {
    const m = paletteMatches();
    if (ev.key === "ArrowDown") { S.paletteSel++; renderPalette(); ev.preventDefault(); }
    else if (ev.key === "ArrowUp") { S.paletteSel--; renderPalette(); ev.preventDefault(); }
    else if (ev.key === "Enter" && m[S.paletteSel]) { closePalette(); setTask(m[S.paletteSel].task_id); }
    else if (ev.key === "Escape") closePalette();
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.metaKey && ev.key.toLowerCase() === "k") { ev.preventDefault(); openPalette(); return; }
    if (!$("#palette").hidden || ev.metaKey || ev.ctrlKey || ev.altKey) return;
    if (/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) return;
    const k = ev.key.toLowerCase();
    const map = { r: "pull", e: "paste", 1: "retry_budget", 2: "hidden_best_of_n", 3: "test_gated_reveal", 4: "typed_holes_patch" };
    if (map[k]) { ev.preventDefault(); run(map[k]); }
    else if (k === "o") setTab("overview");
    else if (k === "c") setTab("compare");
    else if (k === "t" || k === "/") { ev.preventDefault(); openPalette(); }
    else if (k === "p") togglePeek();
    else if (k === "f") setFeedback(REAL() ? "complete" : "realistic");
    else if (k === "[" || k === "]") {
      const i = S.tasks.indexOf(S.task) + (k === "]" ? 1 : -1);
      setTask(S.tasks[(i + S.tasks.length) % S.tasks.length].task_id);
    }
  });
  // tooltips
  const tip = $("#tooltip");
  document.addEventListener("mouseover", (ev) => {
    const el = ev.target.closest("[data-tip]");
    if (!el) { tip.hidden = true; return; }
    tip.textContent = el.dataset.tip; tip.hidden = false;
  });
  document.addEventListener("mousemove", (ev) => {
    if (tip.hidden) return;
    const x = Math.min(ev.clientX + 14, innerWidth - tip.offsetWidth - 8);
    tip.style.left = `${x}px`; tip.style.top = `${ev.clientY + 16}px`;
  });
}

function setFeedback(mode) {
  if (mode === S.feedback) return;
  if (mode === "realistic" && !(S.boot.phase3 && (S.boot.phase3.order || []).length)) {
    $("#stage").insertAdjacentHTML("afterbegin", `<div class="empty" style="margin-bottom:12px">No Phase 3 results yet. Run python -m harness.evaluate_realistic and python -m analysis.phase3.</div>`);
    return;
  }
  S.feedback = mode; S.runId++; S.busy = false;
  renderFeedback(); renderTaskHead(); renderStage(); syncHash();
}

function renderFeedback() {
  document.querySelectorAll("[data-feedback]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.feedback === S.feedback));
}

function togglePeek() {
  S.peek = !S.peek;
  $("#stage").classList.toggle("peeking", S.peek);
  if (REAL() && S.tab !== "overview" && S.tab !== "compare" && !S.busy) { renderStage(); return; }
  const out = $("#patch-out");
  if (out) out.classList.toggle("peeking", S.peek);
  const b = $("[data-action=peek]");
  if (b) { b.setAttribute("aria-pressed", S.peek); b.firstChild.textContent = `${S.peek ? "Hide" : "Peek"} behind the glass `; }
}

function run(what) {
  if (what === "pull") return runPull();
  if (what === "paste") return runPaste();
  if (PATCHES[what]) return runPatch(what);
}

// ------------------------------------------------------------------------------- boot
async function main() {
  bindEvents(); renderKeys();
  try {
    S.boot = await api("/api/bootstrap");
  } catch (e) {
    $("#stage").innerHTML = errorCard(e);
    return;
  }
  S.tasks = S.boot.tasks;
  S.tasks.forEach((t) => S.byId.set(t.task_id, t));
  const h = new URLSearchParams(location.hash.slice(1));
  const tid = S.byId.has(h.get("task")) ? h.get("task") : (S.byId.has("he_fix_spaces") ? "he_fix_spaces" : S.tasks[0].task_id);
  const tab = TABS.some((t) => t.id === h.get("tab")) ? h.get("tab") : "overview";
  S.tab = tab;
  if (h.get("fb") === "realistic" && S.boot.phase3 && (S.boot.phase3.order || []).length) S.feedback = "realistic";
  renderTotals(); renderTabs(); renderFeedback();
  setTask(tid);
  addEventListener("hashchange", () => {
    const q = new URLSearchParams(location.hash.slice(1));
    if (S.byId.has(q.get("task")) && q.get("task") !== S.task.task_id) setTask(q.get("task"));
    if (TABS.some((t) => t.id === q.get("tab")) && q.get("tab") !== S.tab) setTab(q.get("tab"));
  });
}

main();
