"use strict";
// Safety rule: text from a model, ticket or PR is only ever inserted as a DOM text node, never parsed as HTML.

const state = { runs: [], selected: null, detail: null, tab: "report", job: null, config: {}, draft: {} };

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

function findingCard(finding, index, triage) {
  const sev = el("span", { class: "sev " + finding.severity, text: finding.severity.toUpperCase() });
  const where = finding.line ? `${finding.file}:${finding.line}` : `${finding.file} (no line)`;
  const badges = [];
  if ((finding.found_by || []).length) badges.push(el("span", { class: "chip", text: "found by " + finding.found_by.join(" + ") }));
  if (finding.source === "tool") badges.push(el("span", { class: "chip ok", text: "static analysis" }));
  else if (finding.verification === "supported") badges.push(el("span", { class: "chip ok", text: "verified" }));
  else if (finding.verification === "uncertain") badges.push(el("span", { class: "chip warn", text: "verifier unsure" }));
  else if (finding.verification_note) badges.push(el("span", { class: "chip warn", text: "not verified" }));
  const card = el("div", { class: "card" },
    el("h3", {}, sev, finding.title),
    el("div", { class: "meta", text: `${finding.category} · ${where}` }),
    badges.length ? el("div", { class: "summary" }, badges) : null,
    el("p", {}, inline(finding.explanation)));
  if (finding.verification_note) card.append(el("div", { class: "muted", text: "Verifier: " + finding.verification_note }));
  for (const ev of finding.evidence || []) card.append(el("div", { class: "muted", text: `Evidence from ${ev.source}:` }), el("pre", { text: ev.quote }));
  const problems = (state.detail.result.problems || []).filter((p) => p.finding_index === index);
  for (const p of problems) card.append(el("div", { class: "problem", text: `Not confirmed (${p.kind}): ${p.message}` }));

  const draft = state.draft[index] || (state.draft[index] = { decision: triage[index]?.decision || "", note: triage[index]?.note || "" });
  const accept = el("button", { text: "Accept" });
  const dismiss = el("button", { text: "Dismiss" });
  const note = el("input", { placeholder: "Optional note", value: draft.note });
  const paint = () => {
    accept.className = draft.decision === "accepted" ? "on-accept" : "";
    dismiss.className = draft.decision === "dismissed" ? "on-dismiss" : "";
  };
  accept.onclick = () => { draft.decision = draft.decision === "accepted" ? "" : "accepted"; paint(); };
  dismiss.onclick = () => { draft.decision = draft.decision === "dismissed" ? "" : "dismissed"; paint(); };
  note.oninput = () => { draft.note = note.value; };
  paint();
  card.append(el("div", { class: "triage" }, accept, dismiss, note));
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

function findingsView(detail) {
  const result = detail.result;
  if (!result) return el("p", { class: "hint", text: "No result yet." });
  if (result.status === "failed") return el("div", { class: "banner bad", text: `Review failed (${result.error.kind}): ${result.error.message}` });
  const extras = [profileView(result), toolsView(result), passesView(result), checklistView(result)];
  if (!result.findings.length) return el("div", {}, ...extras.filter(Boolean),
    el("p", { text: "No findings were reported. That is the model's claim, not a guarantee." }), dismissedView(result));
  const triage = {};
  for (const d of (detail.triage?.decisions || [])) triage[d.finding_index] = d;
  const reviewer = el("input", { placeholder: "Your name", value: detail.triage?.reviewer || "" });
  const status = el("span", { class: "muted" });
  const save = el("button", { class: "primary", text: "Save my decisions", onclick: async () => {
    const decisions = Object.entries(state.draft).filter(([, d]) => d.decision)
      .map(([i, d]) => ({ finding_index: Number(i), decision: d.decision, note: d.note || "" }));
    try {
      await api(`/api/runs/${enc(state.selected)}/triage`, { reviewer: reviewer.value, decisions });
      status.textContent = `Saved ${decisions.length} decision(s) to triage.json and report-triaged.md`;
    } catch (e) { status.textContent = "Could not save: " + e.message; }
  } });
  return el("div", {}, ...extras.filter(Boolean),
    el("h2", { text: "Findings" }),
    el("p", { class: "muted", text: "You decide. Accept a finding if it is a real problem, dismiss it if not." }),
    result.findings.map((f, i) => findingCard(f, i, triage)),
    el("div", { class: "triage" }, reviewer, save, status),
    dismissedView(result));
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

function showEmpty() {
  $view().replaceChildren(
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

function renderRunList() {
  const ul = document.getElementById("runs");
  ul.replaceChildren(...state.runs.map((r) => {
    const sub = [r.model, r.pipeline === "multi" && "multi-pass", r.head_sha && "commit " + r.head_sha, r.findings != null && `${r.findings} finding(s)`, r.triaged && "triaged"].filter(Boolean).join(" · ");
    return el("li", { class: r.name === state.selected ? "sel" : "", onclick: () => selectRun(r.name) },
      el("div", { class: "title" }, statusDot(r.status), r.case_id),
      el("div", { class: "sub", text: `${r.status} · ${r.created_at.replace("T", " ").slice(0, 19)}` }),
      el("div", { class: "sub", text: sub }));
  }));
  if (!state.runs.length) ul.append(el("li", { class: "hint", text: "No runs yet." }));
}

function renderDetail() {
  const d = state.detail;
  if (!d) return;
  const s = d.summary;
  const tabs = [["report", "Report"], ["findings", "Findings"], ["timeline", "Timeline"], ["raw", "Raw"]];
  let body;
  if (state.tab === "report") body = d.report ? renderMarkdown(d.report) : el("p", { class: "hint", text: s.status === "running" ? "Still running…" : "No report." });
  else if (state.tab === "findings") body = findingsView(d);
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
  if (state.selected !== name) state.draft = {};
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
    if (job.status === "done" && job.run_name) { state.job = null; await refreshRuns(); state.tab = "report"; await selectRun(job.run_name); }
    else if (job.status === "failed") { state.job = null; await refreshRuns(); }
  } catch (e) { state.job = null; }
}

async function refreshRuns() {
  try { state.runs = await api("/api/runs"); renderRunList(); } catch (e) { /* server stopped */ }
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
    state.job = out.job; state.selected = null; renderRunList();
    await pollJob();
  } catch (e) {
    $view().replaceChildren(el("div", { class: "banner bad", text: e.message }));
  } finally { button.disabled = false; }
}

async function init() {
  document.getElementById("new-review").addEventListener("submit", startReview);
  try {
    state.config = await api("/api/config");
    const c = state.config;
    document.getElementById("cfg").textContent = c.model
      ? `new reviews will use: ${c.model} · ${c.pipeline || "multi"}-pass · prompt ${c.prompt_version}` : "";
    if (!state.config.can_start) document.getElementById("start").disabled = true;
  } catch (e) { /* ignore */ }
  showEmpty();
  await refreshRuns();
  const link = location.hash.match(/^#run=([^&]+)(?:&tab=(\w+))?/);  // deep link: #run=<name>&tab=findings
  if (link) {
    if (["report", "findings", "timeline", "raw"].includes(link[2])) state.tab = link[2];
    await selectRun(decodeURIComponent(link[1]));
  }
  setInterval(refreshRuns, 3000);
  setInterval(() => {
    if (state.job) pollJob();
    else if (state.detail && state.detail.summary.status === "running" && state.selected) loadDetail();
  }, 1200);
}

document.addEventListener("DOMContentLoaded", init);
