"use strict";
// Safety rule: text from a model, ticket or PR is only ever inserted as a DOM text node, never parsed as HTML.

const RECENT_REVIEWS = 3;  // individual reviews listed before "show older reviews"

const state = {
  more: false, runs: [], groups: [], selected: null, detail: null, tab: "review", job: null, config: {}, draft: {},
  filter: "", open: {}, view: "run", picked: new Set(), comparison: null, scope: "all", stats: null,
};

function el(tag, props, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) if (c != null) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  return node;
}

async function api(path, body) {
  const opts = body === undefined ? {} : {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Requested-With": "review-agent-ui" },
    body: JSON.stringify(body),
  };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

const enc = (name) => name.split("/").map(encodeURIComponent).join("/");

// ----------------------------------------------------------------- markdown (to DOM)

function inline(text) {
  const frag = document.createDocumentFragment();
  for (const part of text.split(/(`[^`]+`|\*\*[^*]+\*\*)/)) {
    if (!part) continue;
    if (part.startsWith("`") && part.endsWith("`") && part.length > 2) frag.append(el("code", { text: part.slice(1, -1) }));
    else if (part.startsWith("**") && part.endsWith("**") && part.length > 4) frag.append(el("strong", { text: part.slice(2, -2) }));
    else frag.append(document.createTextNode(part));
  }
  return frag;
}

function renderMarkdown(text) {
  const root = el("div", { class: "md" });
  const lines = text.split("\n");
  let i = 0;
  const isBlock = (l) => /^(#{1,6} |> ?|[-*] |`{3,}|\|)/.test(l);
  const isRow = (l) => /^\|.*\|\s*$/.test(l);
  const cellsOf = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  while (i < lines.length) {
    const line = lines[i];
    if (/^`{3,}/.test(line)) {
      const fence = line.match(/^`+/)[0];
      const body = [];
      for (i++; i < lines.length && !lines[i].startsWith(fence); i++) body.push(lines[i]);
      i++;
      root.append(el("pre", {}, el("code", { text: body.join("\n") })));
    } else if (/^#{1,6} /.test(line)) {
      const level = Math.min(line.match(/^#+/)[0].length, 3);
      root.append(el("h" + level, {}, inline(line.replace(/^#+ /, ""))));
      i++;
    } else if (isRow(line) && i + 1 < lines.length && /^\|[\s:|-]+\|\s*$/.test(lines[i + 1])) {
      // A Markdown table: header row, separator row, then body rows. Cells are text nodes only.
      const head = cellsOf(line);
      const rows = [];
      for (i += 2; i < lines.length && isRow(lines[i]); i++) rows.push(cellsOf(lines[i]));
      root.append(el("table", {},
        el("thead", {}, el("tr", {}, head.map((h) => el("th", {}, inline(h))))),
        el("tbody", {}, rows.map((r) => el("tr", {}, r.map((c) => el("td", {}, inline(c))))))));
    } else if (/^> ?/.test(line)) {
      const body = [];
      for (; i < lines.length && /^> ?/.test(lines[i]); i++) body.push(lines[i].replace(/^> ?/, ""));
      root.append(el("blockquote", {}, inline(body.join(" "))));
    } else if (/^[-*] /.test(line)) {
      const ul = el("ul");
      for (; i < lines.length && /^[-*] /.test(lines[i]); i++) ul.append(el("li", {}, inline(lines[i].replace(/^[-*] /, ""))));
      root.append(ul);
    } else if (!line.trim()) {
      i++;
    } else {
      const body = [];
      for (; i < lines.length && lines[i].trim() && !isBlock(lines[i]); i++) body.push(lines[i]);
      root.append(el("p", {}, inline(body.join(" "))));
    }
  }
  return root;
}

// -------------------------------------------------------------------------- pieces

function statusDot(status) { return el("span", { class: "dot " + status, title: status }); }

function eventTable(events) {
  if (!events.length) return el("p", { class: "hint", text: "No events recorded." });
  const rows = events.filter((e) => e.status !== "start" || e.stage.startsWith("model") || e.stage.startsWith("pass:")).map((e) => {
    const bits = [];
    if (e.seconds != null) bits.push(`${e.seconds}s`);
    const d = e.data || {};
    if (d.prompt_tokens != null) bits.push(`${d.prompt_tokens} in / ${d.completion_tokens} out tokens`);
    if (d.findings != null) bits.push(`${d.findings} finding(s)`);
    if (d.warnings != null) bits.push(`${d.warnings} tool warning(s), ${d.on_changed_lines} on changed lines`);
    if (d.problems) bits.push(`${d.problems} unconfirmed`);
    return el("tr", {},
      el("td", { text: e.ts.slice(11, 19) }),
      el("td", { class: "st " + e.status, text: e.status }),
      el("td", { text: e.stage }),
      el("td", { text: e.message + (bits.length ? "  (" + bits.join(", ") + ")" : "") }));
  });
  return el("table", {}, el("tbody", {}, rows));
}

function findingDetail(finding, index) {
  const sev = el("span", { class: "sev " + finding.severity, text: finding.severity.toUpperCase() });
  const where = finding.line ? `${finding.file}:${finding.line}` : `${finding.file} (no line)`;
  const badges = [];
  if (finding.criterion != null) badges.push(el("span", { class: "chip bad", text: `requirement ${finding.criterion} not met` }));
  if ((finding.found_by || []).length) badges.push(el("span", { class: "chip", text: "found by " + finding.found_by.join(" + ") }));
  if (finding.source === "tool") badges.push(el("span", { class: "chip ok", text: "static analysis" }));
  else if (finding.verification === "supported") badges.push(el("span", { class: "chip ok", text: "verified" }));
  else if (finding.verification === "uncertain") badges.push(el("span", { class: "chip warn", text: "verifier unsure" }));
  else if (finding.verification_note) badges.push(el("span", { class: "chip warn", text: "not verified" }));
  const card = el("div", {},
    el("h3", { class: "ftitle-big" }, sev, finding.title),
    el("div", { class: "meta", text: `${finding.category} · ${where}` }),
    badges.length ? el("div", { class: "summary" }, badges) : null,
    el("p", {}, inline(finding.explanation)));
  if (finding.verification_note) card.append(el("div", { class: "muted", text: "Verifier: " + finding.verification_note }));
  for (const ev of finding.evidence || []) card.append(el("div", { class: "muted", text: `Evidence from ${ev.source}:` }), el("pre", { text: ev.quote }));
  const problems = (state.detail.result.problems || []).filter((p) => p.finding_index === index);
  for (const p of problems) card.append(el("div", { class: "problem", text: `Not confirmed (${p.kind}): ${p.message}` }));
  return card;
}

const VERDICT = { met: ["MET", "ok"], not_met: ["NOT MET", "bad"], cannot_determine: ["CANNOT DETERMINE", "warn"] };

function checklistView(result) {
  if (!(result.criteria || []).length) return null;
  const probs = (i) => (result.problems || []).filter((p) => p.criterion_index === i);
  return el("div", {},
    el("h2", { text: "Requirements checklist" }),
    result.criteria.map((c, i) => {
      const [label, cls] = VERDICT[c.verdict] || [c.verdict, ""];
      const card = el("div", { class: "card" },
        el("h3", {}, el("span", { class: "chip " + cls, text: label }), ` ${c.number}. ${c.text}`),
        el("p", {}, inline(c.explanation)));
      for (const ev of c.evidence || []) card.append(el("div", { class: "muted", text: `Evidence from ${ev.source}:` }), el("pre", { text: ev.quote }));
      if (c.file) card.append(el("div", { class: "meta", text: `Where: ${c.file}${c.line ? ":" + c.line : ""}` }));
      for (const p of probs(i)) card.append(el("div", { class: "problem", text: `Not confirmed (${p.kind}): ${p.message}` }));
      return card;
    }));
}

function passesView(result) {
  if (!(result.passes || []).length) return null;
  const rows = result.passes.map((p) => el("tr", {},
    el("td", { text: p.name }), el("td", { class: "st " + (p.status === "ok" ? "done" : p.status === "failed" ? "error" : "warn"), text: p.status }),
    el("td", { text: p.duration_s != null ? p.duration_s + " s" : "" }),
    el("td", { text: p.prompt_tokens != null ? `${p.prompt_tokens} / ${p.completion_tokens}` : "" }),
    el("td", { text: p.message || (p.name === "verify" ? `${p.findings} dismissed` : `${p.findings} candidate(s)`) })));
  return el("div", {}, el("h2", { text: "Specialist passes" }),
    el("table", {}, el("thead", {}, el("tr", {}, ["Pass", "Status", "Time", "Tokens in / out", "Result"].map((h) => el("th", { text: h })))), el("tbody", {}, rows)));
}

function profileView(result) {
  const p = result.change_profile;
  if (!p || !p.files_changed) return null;
  const langs = Object.entries(p.languages || {}).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([k, v]) => `${k} x${v}`).join(", ");
  return el("div", {}, el("h2", { text: "Change profile" }),
    el("div", { class: "summary" },
      el("span", { class: "chip", text: `${p.files_changed} file(s)` }), el("span", { class: "chip", text: `+${p.lines_added} / -${p.lines_removed} lines` }),
      el("span", { class: "chip", text: `${p.source_files} source · ${p.test_files} test` }), el("span", { class: "chip", text: langs })),
    (p.hints || []).map((h) => el("div", { class: "banner warn", text: h })));
}

function contextView(result) {
  if (!(result.context || []).length) return null;
  return el("div", {}, el("h2", { text: "Repository context" }),
    el("p", { class: "muted", text: "Code outside the change that the model was shown (callers, tests, the class). Found by matching function names, so it can match the wrong function." }),
    el("ul", {}, result.context.map((line) => el("li", {}, inline(line)))));
}

function toolsView(result) {
  if (!(result.tools || []).length) return null;
  const rows = result.tools.map((t) => el("tr", {},
    el("td", { text: `${t.name} ${t.version || ""}` }),
    el("td", { class: "st " + (t.status === "ok" ? "done" : t.status === "failed" ? "error" : "warn"), text: t.status }),
    el("td", { text: String(t.files_checked) }), el("td", { text: String(t.total_findings) }),
    el("td", { text: String(t.findings_on_changed_lines) }), el("td", { text: t.message || "" })));
  return el("div", {}, el("h2", { text: "Automated checks (static analysis)" }),
    el("p", { class: "muted", text: "Deterministic tools, not a model. Warnings on lines this PR changed are reported as findings; others are counted, not blamed on this change." }),
    el("table", {}, el("thead", {}, el("tr", {}, ["Tool", "Status", "Files", "Warnings", "On changed lines", "Note"].map((h) => el("th", { text: h })))), el("tbody", {}, rows)));
}

function dismissedView(result) {
  if (!(result.dismissed || []).length) return null;
  return el("div", {}, el("h2", { text: "Dismissed by verification" }),
    el("p", { class: "muted", text: "Judged unsupported by the verifier. Listed so nothing disappears silently; you can overrule it." }),
    result.dismissed.map((d) => el("div", { class: "card" },
      el("h3", { text: d.finding.title }),
      el("div", { class: "meta", text: `${d.finding.file}${d.finding.line ? ":" + d.finding.line : ""} · found by ${(d.finding.found_by || []).join(" + ")}` }),
      el("p", { text: "Verifier: " + d.reason }))));
}

function detailsView(detail) {
  const result = detail.result;
  if (!result) return el("p", { class: "hint", text: "No result yet." });
  if (result.status === "failed") return el("div", { class: "banner bad", text: `Review failed (${result.error.kind}): ${result.error.message}` });
  return el("div", {}, ...[profileView(result), contextView(result), toolsView(result), passesView(result), checklistView(result), dismissedView(result)].filter(Boolean));
}

// ------------------------------------------------------------------- review screen
// Findings on the left (worst first), the selected finding in the middle, the ticket requirements on the right.
// Decisions are saved as you make them; j/k move, a accepts, d dismisses.

const SEV_RANK = { critical: 0, high: 1, medium: 2, low: 3 };
const SEV_SHORT = { critical: "CRIT", high: "HIGH", medium: "MED", low: "LOW" };
const DECISION_WORD = { accepted: "Accepted", dismissed: "Dismissed" };
let saveEl = null;
let toastTimer = null;

function showToast(text, undo) {
  document.querySelector(".toast")?.remove();
  clearTimeout(toastTimer);
  const toast = el("div", { class: "toast" }, el("span", { text }));
  if (undo) toast.append(el("button", { text: "Undo", onclick: () => { toast.remove(); undo(); } }));
  document.body.append(toast);
  toastTimer = setTimeout(() => toast.remove(), 5000);
}

function setSaveText(text) { state.saveText = text; if (saveEl) saveEl.textContent = text; }

async function saveTriage() {
  const run = state.selected;
  const decisions = Object.entries(state.draft).filter(([, d]) => d.decision)
    .map(([i, d]) => ({ finding_index: Number(i), decision: d.decision, note: d.note || "" }));
  setSaveText("Saving…");
  try {
    await api(`/api/runs/${enc(run)}/triage`, { reviewer: state.reviewer, decisions });
    setSaveText(`Saved ${new Date().toTimeString().slice(0, 8)}`);
  } catch (e) { setSaveText("Could not save: " + e.message); }
}

function reviewView(detail) {
  const result = detail.result;
  if (!result) return el("p", { class: "hint", text: detail.summary.status === "running" ? "Still running…" : "No result yet." });
  if (result.status === "failed") return el("div", { class: "banner bad", text: `Review failed (${result.error.kind}): ${result.error.message}` });
  const findings = result.findings;
  const triage = {};
  for (const d of (detail.triage?.decisions || [])) triage[d.finding_index] = d;
  findings.forEach((f, i) => { if (!state.draft[i]) state.draft[i] = { decision: triage[i]?.decision || "", note: triage[i]?.note || "" }; });
  if (state.reviewer == null) state.reviewer = detail.triage?.reviewer || localStorage.getItem("reviewer") || "";
  const order = findings.map((_, i) => i).sort((a, b) => (SEV_RANK[findings[a].severity] ?? 9) - (SEV_RANK[findings[b].severity] ?? 9) || a - b);
  if (state.sel == null || !findings[state.sel]) state.sel = order.length ? order[0] : null;
  const box = el("div", { class: "review" });

  const decide = (index, value) => {
    const draft = state.draft[index];
    const before = draft.decision;
    draft.decision = before === value ? "" : value;
    paint(); saveTriage();
    showToast(draft.decision ? `${DECISION_WORD[draft.decision]}: ${findings[index].title.length > 50 ? findings[index].title.slice(0, 50) + "…" : findings[index].title}` : "Decision cleared", () => { draft.decision = before; paint(); saveTriage(); });
  };
  const move = (step) => {
    if (!order.length) return;
    const at = order.indexOf(state.sel);
    state.sel = order[Math.min(order.length - 1, Math.max(0, at + step))];
    paint();
  };
  state.review = { decide: (v) => state.sel != null && decide(state.sel, v), move };

  const left = () => {
    const decided = findings.filter((_, i) => state.draft[i].decision).length;
    const fill = el("div", { class: "fill" });
    fill.style.width = (findings.length ? Math.round((decided / findings.length) * 100) : 0) + "%";
    const reviewer = el("input", { placeholder: "Your name", value: state.reviewer });
    reviewer.oninput = () => { state.reviewer = reviewer.value; localStorage.setItem("reviewer", reviewer.value); };
    reviewer.onchange = () => { if (decided) saveTriage(); };
    return el("div", { class: "rv-left" },
      el("h2", { text: `Findings · ${decided} of ${findings.length} decided` }),
      el("div", { class: "bar" }, el("div", { class: "track" }, fill)),
      order.map((i) => {
        const f = findings[i];
        const d = state.draft[i].decision;
        return el("div", { class: "frow" + (i === state.sel ? " sel" : ""), onclick: () => { state.sel = i; paint(); } },
          el("span", { class: "mark " + (d || "none"), text: d === "accepted" ? "✓" : d === "dismissed" ? "✕" : "○", title: d || "undecided" }),
          el("div", { class: "ftext" },
            el("div", {}, el("span", { class: "sev " + f.severity, text: SEV_SHORT[f.severity] || f.severity.toUpperCase() }), f.title),
            el("div", { class: "muted", text: f.line ? `${f.file}:${f.line}` : f.file })));
      }),
      el("div", { class: "reviewer" }, el("label", { class: "muted", text: "Reviewer" }), reviewer));
  };

  const middle = () => {
    if (!findings.length) return el("div", { class: "rv-mid" }, el("p", { text: "No findings were reported. That is the model's claim, not a guarantee." }));
    const draft = state.draft[state.sel];
    const note = el("input", { placeholder: "Optional note", value: draft.note });
    note.oninput = () => { draft.note = note.value; clearTimeout(note.timer); note.timer = setTimeout(() => { if (draft.decision) saveTriage(); }, 600); };
    saveEl = el("span", { class: "muted", text: state.saveText || "Decisions are saved as you make them." });
    return el("div", { class: "rv-mid" },
      findingDetail(findings[state.sel], state.sel),
      el("div", { class: "triage" },
        el("button", { class: draft.decision === "accepted" ? "on-accept" : "", text: "Accept (a)", onclick: () => decide(state.sel, "accepted") }),
        el("button", { class: draft.decision === "dismissed" ? "on-dismiss" : "", text: "Dismiss (d)", onclick: () => decide(state.sel, "dismissed") }),
        note),
      el("div", { class: "triage" },
        el("button", { text: "◀ Previous (k)", onclick: () => move(-1) }), el("button", { text: "Next (j) ▶", onclick: () => move(1) }), saveEl));
  };

  const right = () => {
    const criteria = result.criteria || [];
    const rows = criteria.map((c) => {
      const [label, cls] = VERDICT[c.verdict] || [c.verdict, ""];
      const linked = findings.findIndex((f) => f.criterion === c.number);
      return el("div", { class: "req" + (linked >= 0 ? " link" : ""), onclick: () => { if (linked >= 0) { state.sel = linked; paint(); } }, title: linked >= 0 ? "Show the finding for this requirement" : "" },
        el("span", { class: "chip " + cls, text: label }), el("div", { text: `${c.number}. ${c.text}` }));
    });
    return el("div", { class: "rv-right" }, el("h2", { text: "Ticket requirements" }),
      rows.length ? rows : el("p", { class: "hint", text: "No ticket requirements were available for this review." }));
  };

  function paint() { box.replaceChildren(left(), middle(), right()); }
  paint();
  return box;
}

function rawView(detail) {
  const run = detail.run;
  if (!run) return el("p", { class: "hint", text: "No run record yet." });
  const facts = [["Model", `${run.settings.model} @ ${run.settings.host}`], ["Prompt version", run.prompt_version],
    ["Temperature / seed", `${run.settings.temperature} / ${run.settings.seed}`], ["Tokens", `${run.prompt_tokens} in / ${run.completion_tokens} out`],
    ["Model time", run.duration_s != null ? run.duration_s + " s" : "n/a"], ["Finish reason", run.done_reason || "n/a"]];
  const answers = (run.passes || []).length
    ? run.passes.map((p) => el("div", {}, el("h2", { text: `Raw answer of pass "${p.name}"` }),
        el("pre", { text: p.skipped ? `(skipped: ${p.skipped})` : p.error ? `(failed: ${p.error.kind}: ${p.error.message})` : p.raw_response || "(none)" })))
    : [el("h2", { text: "Raw model response (exactly as received)" }), el("pre", { text: run.raw_response || "(none)" })];
  return el("div", {},
    el("table", {}, el("tbody", {}, facts.map(([k, v]) => el("tr", {}, el("th", { text: k }), el("td", { text: String(v) }))))),
    answers);
}

// -------------------------------------------------------------------------- views

function whatItDoes() {
  return el("div", {},
    el("h2", { text: "What this tool does" }),
    el("ol", { class: "steps" },
      el("li", { text: "Reads a GitHub pull request (read-only) and, if you ask, the Jira ticket it links to." }),
      el("li", { text: "Builds one message for the AI model: the requirements, the PR text and the code changes with line numbers." }),
      el("li", { text: "Asks the model to compare the code with the requirements and report only what it can quote evidence for." }),
      el("li", { text: "Checks the answer: does each cited file, line and quote really exist? Anything unconfirmed is flagged." }),
      el("li", { text: "Shows a report of findings, and says what could not be reviewed." }),
      el("li", { text: "You decide: accept or dismiss each finding. The tool never merges or edits anything." })),
    el("p", { class: "hint", text: "Type a pull request above (for example ebirdyx/shipping-demo#1) and press Review, or pick an earlier run on the left." }));
}

const $view = () => document.getElementById("view");

function matches(run, words) {
  if (!words.length) return true;
  const hay = [run.case_id, run.name, run.status, run.model, run.ticket, run.group, run.pipeline, run.prompt_version].join(" ").toLowerCase();
  return words.every((w) => hay.includes(w));
}

function runRow(r) {
  const sub = [r.model, r.pipeline === "multi" && "multi-pass", r.head_sha && "commit " + r.head_sha, r.findings != null && `${r.findings} finding(s)`, r.triaged && "triaged"].filter(Boolean).join(" · ");
  return el("li", { class: "run" + (r.name === state.selected ? " sel" : ""), onclick: () => selectRun(r.name) },
    el("div", { class: "title" }, statusDot(r.status), r.case_id),
    el("div", { class: "sub", text: `${r.status} · ${r.created_at.replace("T", " ").slice(0, 19)}` }),
    el("div", { class: "sub", text: sub }));
}

// Runs are grouped by the evaluation folder they belong to ("" = a review started on its own).
// A group is collapsed unless it holds the selected run; typing in the filter opens every group that matches.
function renderRunList() {
  const ul = document.getElementById("runs");
  const words = state.filter.toLowerCase().split(/\s+/).filter(Boolean);
  const groups = new Map([["", []]]);
  for (const r of state.runs) {
    if (!groups.has(r.group)) groups.set(r.group, []);
    groups.get(r.group).push(r);
  }
  const rows = [];
  for (const [name, runs] of groups) {
    const shown = runs.filter((r) => matches(r, words));
    if (!shown.length && (words.length || !runs.length)) continue;
    const holdsSelected = runs.some((r) => r.name === state.selected);
    const open = words.length ? true : (name in state.open ? state.open[name] : (name === "" || holdsSelected));
    const info = state.groups.find((g) => g.name === name);
    const title = name === "" ? "Individual reviews" : name;
    const label = info && info.label !== name ? ` (${info.label})` : "";
    rows.push(el("li", { class: "group", onclick: () => { state.open[name] = !open; renderRunList(); } },
      el("span", { class: "caret", text: open ? "▾" : "▸" }), el("strong", { text: title }),
      el("span", { class: "muted", text: `${label}  ${words.length ? shown.length + " of " + runs.length : runs.length}` })));
    const cap = name === "" && !words.length && !state.more ? RECENT_REVIEWS : Infinity;  // keep the groups below in view
    if (open) for (const r of shown.slice(0, cap)) rows.push(runRow(r));
    if (open && shown.length > cap) rows.push(el("li", { class: "hint", onclick: () => { state.more = true; renderRunList(); }, text: `show ${shown.length - cap} older reviews...` }));
  }
  ul.replaceChildren(...rows);
  if (!rows.length) ul.append(el("li", { class: "hint", text: state.runs.length ? "No run matches the filter." : "No runs yet." }));
}

// ------------------------------------------------------------------------------- overview

const SCOPES = [["all", "All runs"], ["reviews", "Individual reviews"], ["evaluations", "Evaluation runs"]];

function viewTabs(current) {
  return el("div", { class: "viewtabs" },
    [["overview", "Overview", showOverview], ["evaluations", "Evaluations", showEvaluations]].map(([id, label, go]) =>
      el("button", { class: current === id ? "on" : "", text: label, onclick: go })));
}

function statCard(label, value, note, tone) {
  return el("div", { class: "stat" + (tone ? " " + tone : "") }, el("div", { class: "label", text: label }),
    el("div", { class: "value", text: String(value) }), note ? el("div", { class: "note", text: note }) : null);
}

// One horizontal bar per row; the note says how many of those findings people accepted.
function barPanel(title, rows, total, tone) {
  const max = Math.max(1, ...rows.map((r) => r.n));
  const body = rows.slice(0, 8).map((r) => {
    const decided = r.accepted + r.dismissed;
    const note = `${r.n} of ${total}` + (decided ? ` · ${r.accepted} of ${decided} accepted` : "");
    const fill = el("div", { class: "fill" + (tone ? " " + r.name : "") });
    fill.style.width = Math.round((r.n / max) * 100) + "%";  // set through the DOM: the page's CSP forbids inline style attributes
    return el("div", { class: "bar" },
      el("div", { class: "head" }, el("span", { text: r.name.replace(/_/g, " ") }), el("span", { text: note })),
      el("div", { class: "track" }, fill));
  });
  return el("div", { class: "panel" }, el("h3", { text: title }), body.length ? body : el("p", { class: "hint", text: "Nothing yet." }));
}

function renderOverview() {
  const st = state.stats;
  const pills = el("div", { class: "pills" }, SCOPES.map(([id, label]) =>
    el("button", { class: state.scope === id ? "on" : "", text: label, onclick: async () => { state.scope = id; await showOverview(); } })));
  let body;
  if (!st) body = el("p", { class: "hint", text: "Loading..." });
  else {
    const accepted = st.triaged ? `${st.accepted} of ${st.triaged} accepted` : "no human decisions yet";
    body = el("div", {},
      el("div", { class: "stats" },
        statCard("Runs", st.runs, `${st.individual_runs} individual · ${st.evaluation_runs} in evaluations`),
        statCard("Findings", st.findings, `${st.tool_backed} backed by a tool`),
        statCard("High or critical", st.high, st.findings ? `${Math.round((st.high / st.findings) * 100)}% of findings` : "", st.high ? "bad" : ""),
        statCard("Dismissed by verifier", st.verifier_dismissed, "claims the verifier did not confirm"),
        statCard("Human decisions", st.triaged, accepted, st.triaged ? "good" : "")),
      el("div", { class: "panels" },
        barPanel("By severity", st.by_severity, st.findings, true),
        barPanel("By category", st.by_category, st.findings),
        barPanel("By who found it (a finding can have several)", st.by_found_by, st.findings)));
  }
  $view().replaceChildren(viewTabs("overview"), pills, body, whatItDoes());
}

async function showOverview() {
  state.view = "overview"; state.selected = null; state.detail = null; state.job = null;
  history.replaceState(null, "", "#overview");
  renderRunList();
  renderOverview();
  try { state.stats = await api("/api/stats?scope=" + state.scope); } catch (e) { state.stats = null; }
  if (state.view === "overview") renderOverview();
}

// ------------------------------------------------------------------------------- evaluations

function configSummary(c) {
  if (!c) return "no recorded configuration (made before eval-run recorded it)";
  const bits = [c.pipeline === "multi" ? "multi-pass" : "single pass", c.prompt_version, c.model];
  if (c.pipeline === "multi") bits.push(`tools ${(c.tools || []).length ? c.tools.join("+") : "off"}`, `context ${c.context ? "on" : "off"}`, `verifier ${c.verify ? "on" : "off"}`);
  bits.push(`${c.repeat} repeat(s)`);
  return bits.join(" · ");
}

async function runComparison() {
  const names = [...state.picked];
  history.replaceState(null, "", "#evaluations&compare=" + names.map(encodeURIComponent).join(","));  // a link you can share or reopen
  try {
    const out = await api("/api/compare?groups=" + names.map(encodeURIComponent).join(","));
    state.comparison = { ok: true, text: out.markdown, configs: out.configs || [] };
  } catch (e) { state.comparison = { ok: false, text: e.message }; }
  renderEvaluations();
}

const pct = (x) => (x == null ? "n/a" : Math.round(x * 100) + "%");

// One card per configuration: the numbers that decide which is better, marked provisional when labels are location-matched.
function comparisonCards(configs) {
  return el("div", { class: "stats" }, configs.map((c) =>
    el("div", { class: "stat" }, el("div", { class: "label", text: c.label + (c.model ? " · " + c.model : "") }),
      el("div", { class: "value", text: "F1 " + pct(c.f1) }),
      el("div", { class: "note", text: `precision ${pct(c.precision)} · recall ${pct(c.recall)}` }),
      el("div", { class: "note", text: `${c.tp} found · ${c.fp} false alarms · ${c.fn} missed` }),
      el("div", { class: "note", text: `${c.runs - c.failed} of ${c.runs} runs completed` + (c.provisional ? " · labels provisional" : "") }))));
}

function renderEvaluations() {
  const compareButton = el("button", { class: "primary", text: "Compare selected" });
  const clearButton = el("button", { text: "Clear" });
  const note = el("span", { class: "muted" });
  const paint = () => {
    const n = state.picked.size;
    compareButton.disabled = n < 1 || n > 6;
    clearButton.disabled = n === 0;
    note.textContent = n ? `${n} selected` : "Tick one or more evaluations (at most 6).";
  };
  compareButton.onclick = () => { compareButton.disabled = true; runComparison(); };
  clearButton.onclick = () => { state.picked.clear(); state.comparison = null; renderEvaluations(); };
  const rows = state.groups.map((g) => {
    const box = el("input", { type: "checkbox" });
    box.checked = state.picked.has(g.name);
    box.onchange = () => { if (box.checked) state.picked.add(g.name); else state.picked.delete(g.name); paint(); };
    const notes = ((g.config && g.config.notes) || []).join(" ");
    return el("tr", {},
      el("td", {}, box),
      el("td", {}, el("strong", { text: g.label }), el("span", { class: "chip " + (g.kind === "evaluation" ? "ok" : ""), text: g.kind }),
        g.label !== g.name ? el("div", { class: "muted", text: g.name }) : null),
      el("td", { text: `${g.completed}/${g.runs} completed${g.failed ? `, ${g.failed} failed` : ""}` }),
      el("td", { text: g.latest.replace("T", " ").slice(0, 16) }),
      el("td", {}, configSummary(g.config), notes ? el("div", { class: "muted", text: notes }) : null),
      el("td", {}, el("button", { text: "Show runs", onclick: () => {
        state.filter = g.name; document.getElementById("filter").value = g.name; state.open[g.name] = true; renderRunList();
      } })));
  });
  const head = el("thead", {}, el("tr", {}, ["", "Evaluation", "Runs", "Latest", "Configuration", ""].map((h) => el("th", { text: h }))));
  const result = state.comparison;
  $view().replaceChildren(...[
    viewTabs("evaluations"),
    el("div", { class: "actionbar" }, compareButton, clearButton, note, el("span", { class: "spacer" }),
      el("span", { class: "muted", text: "Same table as `review-agent eval-compare`. Labels are location-matched unless a labels file exists." })),
    state.groups.length ? el("div", { class: "tablebox" }, el("table", { class: "evals" }, head, el("tbody", {}, rows)))
      : el("p", { class: "hint", text: "No evaluation folders yet. Make one with review-agent eval-run." }),
    result && result.ok && result.configs.length ? comparisonCards(result.configs) : null,
    result ? (result.ok ? renderMarkdown(result.text) : el("div", { class: "banner bad", text: result.text })) : null,
  ].filter(Boolean));
  paint();
}

async function showEvaluations() {
  state.view = "evaluations"; state.selected = null; state.detail = null; state.job = null;
  history.replaceState(null, "", "#evaluations");
  renderRunList();
  await refreshRuns();
  renderEvaluations();
}

function renderDetail() {
  const d = state.detail;
  if (!d) return;
  const s = d.summary;
  const tabs = [["review", "Review"], ["details", "Details"], ["report", "Report"], ["timeline", "Timeline"], ["raw", "Raw"]];
  state.review = null;  // set again by the review screen, so the keys only work there
  let body;
  if (state.tab === "report") body = d.report ? renderMarkdown(d.report) : el("p", { class: "hint", text: s.status === "running" ? "Still running…" : "No report." });
  else if (state.tab === "review") body = reviewView(d);
  else if (state.tab === "details") body = detailsView(d);
  else if (state.tab === "timeline") body = eventTable(d.events);
  else body = rawView(d);
  const ticketChip = s.findings == null ? null : (s.ticket ? "ticket " + s.ticket : "no ticket");
  const chips = [s.model, s.pipeline && s.pipeline + "-pass", "prompt " + s.prompt_version, s.head_sha && "commit " + s.head_sha, ticketChip,
    s.problems != null && `${s.problems} unconfirmed`, s.dismissed ? `${s.dismissed} dismissed by verifier` : null].filter(Boolean);
  $view().replaceChildren(...[
    el("h2", { text: s.case_id }),
    el("div", { class: "summary" }, statusDot(s.status), el("strong", { text: s.status }), chips.map((c) => el("span", { class: "chip", text: c }))),
    s.status === "running" ? el("div", { class: "banner", text: "Running… this page updates by itself." }) : null,
    el("div", { class: "tabs" }, tabs.map(([id, label]) => el("button", { class: state.tab === id ? "on" : "", text: label, onclick: () => {
      state.tab = id; history.replaceState(null, "", `#run=${encodeURIComponent(state.selected)}&tab=${id}`); renderDetail(); } }))),
    body].filter(Boolean));  // replaceChildren turns a null into the text "null", so drop empties
}

async function selectRun(name) {
  state.view = "run";
  if (state.selected !== name) { state.draft = {}; state.sel = null; state.reviewer = null; state.saveText = ""; }
  state.selected = name; state.job = null;
  history.replaceState(null, "", `#run=${encodeURIComponent(name)}&tab=${state.tab}`);
  renderRunList();
  await loadDetail();
}

async function loadDetail() {
  if (!state.selected) return;
  try { state.detail = await api(`/api/runs/${enc(state.selected)}`); renderDetail(); }
  catch (e) { $view().replaceChildren(el("div", { class: "banner bad", text: e.message })); }
}

function renderJob(job) {
  const view = [el("h2", { text: `Review of ${job.ref}` })];
  if (job.status === "running") view.push(el("div", { class: "banner", text: "Running… this page updates by itself." }));
  if (job.status === "failed") view.push(el("div", { class: "banner bad", text: job.error }));
  view.push(eventTable(job.events));
  $view().replaceChildren(...view);
}

async function pollJob() {
  if (!state.job) return;
  try {
    const job = await api(`/api/jobs/${state.job}`);
    renderJob(job);
    if (job.status === "done" && job.run_name) { state.job = null; await refreshRuns(); state.tab = "review"; await selectRun(job.run_name); }
    else if (job.status === "failed") { state.job = null; await refreshRuns(); }
  } catch (e) { state.job = null; }
}

async function refreshRuns() {
  try {
    const [runs, groups] = await Promise.all([api("/api/runs"), api("/api/groups")]);
    state.runs = runs; state.groups = groups; renderRunList();
  } catch (e) { /* server stopped */ }
}

async function startReview(event) {
  event.preventDefault();
  const button = document.getElementById("start");
  button.disabled = true;
  try {
    const out = await api("/api/review", {
      pr: document.getElementById("pr").value, jira: document.getElementById("jira").checked,
      jira_projects: document.getElementById("projects").value,
    });
    state.job = out.job; state.selected = null; state.view = "run"; renderRunList();
    await pollJob();
  } catch (e) {
    $view().replaceChildren(el("div", { class: "banner bad", text: e.message }));
  } finally { button.disabled = false; }
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  document.getElementById("theme").textContent = theme === "dark" ? "☀ Light" : "☾ Dark";
}

async function init() {
  applyTheme(localStorage.getItem("theme") === "light" ? "light" : "dark");  // dark unless the user chose light
  document.getElementById("theme").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    localStorage.setItem("theme", next);
    applyTheme(next);
  });
  document.getElementById("new-review").addEventListener("submit", startReview);
  document.getElementById("jira").addEventListener("change", (e) => { document.getElementById("jira-opts").hidden = !e.target.checked; });
  document.addEventListener("keydown", (e) => {  // keyboard triage on the review screen
    if (state.view !== "run" || state.tab !== "review" || !state.review || e.metaKey || e.ctrlKey || e.altKey) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
    const key = e.key.toLowerCase();
    if (key === "j" || key === "arrowdown") state.review.move(1);
    else if (key === "k" || key === "arrowup") state.review.move(-1);
    else if (key === "a") state.review.decide("accepted");
    else if (key === "d") state.review.decide("dismissed");
    else return;
    e.preventDefault();
  });
  document.getElementById("show-overview").addEventListener("click", showOverview);
  document.getElementById("filter").addEventListener("input", (e) => { state.filter = e.target.value; renderRunList(); });
  try {
    state.config = await api("/api/config");
    const c = state.config;
    document.getElementById("cfg").textContent = c.model
      ? `new reviews will use: ${c.model} · ${c.pipeline || "multi"}-pass · prompt ${c.prompt_version}` : "";
    if (!state.config.can_start) document.getElementById("start").disabled = true;
  } catch (e) { /* ignore */ }
  const startHash = location.hash;  // showOverview rewrites it, so read it first
  await refreshRuns();
  await showOverview();
  const evalLink = startHash.match(/^#evaluations(?:&compare=([^&]+))?/);  // deep link: #evaluations&compare=<folder>,<folder>
  if (evalLink) {
    const names = evalLink[1] ? decodeURIComponent(evalLink[1]).split(",").filter(Boolean) : [];
    for (const n of names) state.picked.add(n);
    await showEvaluations();
    if (names.length) await runComparison();
  }
  const link = startHash.match(/^#run=([^&]+)(?:&tab=(\w+))?/);  // deep link: #run=<name>&tab=review
  if (link) {
    if (link[2] === "findings") state.tab = "review";  // old links
    else if (["review", "details", "report", "timeline", "raw"].includes(link[2])) state.tab = link[2];
    await selectRun(decodeURIComponent(link[1]));
  }
  setInterval(refreshRuns, 3000);
  setInterval(() => {
    if (state.job) pollJob();
    else if (state.detail && state.detail.summary.status === "running" && state.selected) loadDetail();
  }, 1200);
}

document.addEventListener("DOMContentLoaded", init);
