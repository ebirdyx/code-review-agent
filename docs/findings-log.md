# Findings log: what we learned while building the agent

Working notes for the report (sections "Réalisation", "AQ & évaluation", "Analyse"), the slides and the hand-over.
Everything here was observed on real runs unless it says otherwise. Dates are 2026 and follow the order we worked in.

## 1. Bugs that only real runs revealed

Our unit tests mock the model, GitHub and Jira, so they only contain the formats we imagined. Running the real thing found
bugs that 450+ tests had not.

| # | What happened | Cause | Fix | Where it showed |
|---|---|---|---|---|
| 1 | A GitHub redirect was treated as success | status below 400 was accepted | status 300 and above is an error; redirects are never followed (a token must not leak to another host) | GitHub connector review |
| 2 | Jira criteria came out wrong | parser took the prose below the "Acceptance criteria" heading; `[KEY] title` was not recognised as a link | stricter section parser; more link forms | real Jira ticket KAN-4 |
| 3 | "No ticket" shown although Jira worked | a typo in the stored `JIRA_BASE_URL` (a dot inside the site name); terminals opened earlier still held the old value | clearer certificate-error message ("site name probably misspelled"), `doctor` command | user's own run |
| 4 | An old ticket stayed in a new snapshot | a failed Jira re-fetch left the previous `ticket.json` in the folder | the snapshot folder is cleaned before writing | found from the user's run |
| 5 | Quotes of numbered criteria flagged as "not found" | the ticket haystack did not contain the rendered numbered list | haystack includes the rendered ticket; `eval-revalidate` re-checks saved runs without a model call | benchmark runs |
| 6 | One bad item threw away a whole pass | the model cited an evidence source outside the allowed list; strict parsing rejected everything | salvage: keep valid findings, drop the bad one visibly (counts as lost coverage); prompt tweak | multi-pass run on a real PR |
| 7 | 270 of 276 static-analysis warnings were noise | Bandit B101 (`assert`) in test files | Bandit ignored in tests, cap of 30 tool findings, visible note | pallets/click#3884 |
| 8 | Syntax errors not classed as errors | Ruff names the rule `invalid-syntax` | severity mapping fixed | real tool output |
| 9 | Report tables looked like raw text in the UI | the Markdown renderer had no table support | tables rendered | screenshot from the user |
| 10 | The verifier pass of Qwen2.5-Coder was lost | field name written without quotes (`verdict:`) | bare keys at the start of a line are quoted, with a visible warning | first real Qwen run |
| 11 | 4 of 6 demo reviews crashed after the model had answered | printing the report to a redirected Windows output failed on a non-breaking hyphen (U+2011) written by the model | output replaces what it cannot show; regression test | ticket-system demo |
| 12 | The code graph said "mentioned in no test function" for code the same PR tests, and listed the callees of the PR's own new tests | the PR's added tests were excluded from the test list and treated as changed functions | tests count as tests (even when added by the PR) and are not the subject of the search; constructors are matched by class name | trying the graph on the real demo branches before any model run |
| 13 | The verifier dismissed a valid remark together with a speculative one | cross-category merging by line joined two unrelated claims (a missing boundary test and an invented missing-authorization worry); the verifier judged the mixed claim and dismissed it | categories differ: merge only when the reports quote the same code, share much of their wording, or one is tool-backed | demo runs of PR 2 and PR 6 (checked against 18 saved runs) |

Lessons: (a) test with the real model early; (b) every parser must keep what is valid and report what it dropped; (c) any
text the model writes can contain any character; (d) setup mistakes (stale terminal, typo) deserve a diagnostic command
rather than a long explanation.

## 2. Windows and tooling pitfalls (for the hand-over)

- A changed environment variable is only seen by a **new** terminal.
- A running `review-agent ui` locks `review-agent.exe`, so `uv sync` or `uv add` fail until it is stopped.
- PowerShell: backticks in strings corrupt text, `Set-Content` can add a BOM; pass file contents through scripts.
- Keys live in user-level environment variables or CI secrets, never in the repository or in a chat.

## 3. Model behaviour (details in `model-comparison-notes.md`)

- gpt-oss:120b (free tier), Qwen2.5-Coder 32B and Qwen3-Coder 30B all found the planted boundary bug on the same PR.
- The checklist is where the weaker models went wrong: both Qwen models marked a violated criterion MET, contradicting their
  own finding. All their quotes existed in the input, so **"grounded" is not "true"**.
- Qwen2.5-Coder wraps its JSON in Markdown fences and once wrote an unquoted field name. The parser tolerates and reports it.
- Qwen3-Coder (3.3B active parameters) matched or beat the 32B model on one PR at a sixth of the cost: one example, do not generalise.
- Measured cost on a 2-line PR (multi-pass, about 9k input tokens): about $0.006 (Qwen2.5-32B) and $0.001 (Qwen3-30B). Our first
  estimate (about $0.002) was wrong for the 32B model.

## 4. The demonstration project (details in `evaluation/results/ticket-system-demo/README.md`)

Six pull requests with an answer key written beforehand: four planted defects, one clean change, one vague requirement.

- **4 of 4 planted defects found**, requirement checklists correct where a requirement was violated.
- The static tools (Ruff, Bandit) independently flagged the swallowed exception and the SQL injection; the model found them too.
- **First clear value of the verifier**: it dismissed 5 candidates, 3 rightly (an invented indentation error, a duplicate import
  that did not exist, a speculative missing-authorization claim). It also dismissed one rule finding for a wrong reason.
- Weaknesses: the vague requirement was not flagged as undetermined; one defect was reported 3 times under different
  categories; the team-rules pass flagged docstrings on 5 of 6 PRs, several wrongly, including the clean PR.

## 5. Design decisions that the findings support

- **Grounded is not true.** The tool checks that file, line and quote exist, never that the conclusion is right. The report
  says so, and the human reviewer decides.
- **Failed, empty and skipped are different.** A failed pass is "findings NOT double-checked", not "clean".
- **Specialist passes give redundancy** (Qwen3-Coder: compliance missed the bug, defects caught it).
- **Deterministic tools next to the model**: tool findings are shown as such and cannot be dismissed by the verifier.
- **Rules are read from the base branch**, so a pull request cannot rewrite the rules that judge it.
- **Model text is untrusted** everywhere it is shown: fenced quotes, neutralised `@mentions` and links in the PR comment.
- **Switchable model**: one flag (`--profile`), same pipeline, validation and report.

## 6. Known limitations

- Static analysis and every measured result are Python only (22 benchmark cases, 6 demo PRs).
- Multi-pass quality has not been benchmarked against single-pass; labels of the benchmark are provisional until a human reviews them.
- Hosted models receive the code: do not use them on confidential code (see the privacy section in `model-comparison-notes.md`).
- The GitHub Actions integration is tested with simulation only; it has not run on a real repository yet.
- Claude/ChatGPT/Gemini comparison not done yet (protocol in `comparison-protocol.md`).

## 7. Improvement backlog (from the findings above)

| # | Improvement | Triggered by | Status |
|---|---|---|---|
| 1 | Merge findings that describe the same defect on the same line across categories | PR #3, #4 reported 3 times | **Done**, tested; replay of saved runs 4 -> 2 findings (#3), 3 -> 2 (#4), 4 -> 2 (#5) |
| 2 | Rules pass: report only clear violations, no restating the docstring as a violation | docstring findings on 5 of 6 PRs | Prompt tightened (`multi_v3`); **only partly effective** (noise gone on #5, #6; still on #1, #4) |
| 3 | Compliance pass: say "cannot determine" when a criterion is vague | PR #6 | Prompt guidance added; **did not work** with gpt-oss. Next idea: a dedicated "open questions" pass |
| 4 | Checklist-consistency check (a criterion MET where a finding sits on its own lines) | both Qwen runs | **Done**, unit-tested with the Qwen case; not yet seen live on a model that makes the mistake |
| 5 | Verifier must judge rule findings (not call them out of scope) | PR #4 dismissal | Prompt fixed in `multi_v3`; did not recur in the second run |
| 6 | Live GitHub Actions run on a real repository | not done | needs repository secrets |
| 7 | Repository context (code graph: callers, callees, tests, class) | beyond-the-diff review in commercial tools | **Done**, tested; first measurement shows no change in detection on the demo (see section 9) |

## 8. Second run after the improvements (details in `evaluation/results/ticket-system-demo/README.md`)

- Cross-category merging is the clear win (one root cause, one finding, every source listed). It is deterministic and was
  checked on saved runs without any model call.
- Prompt-only fixes had mixed effects: a model's judgement cannot be forced by wording. Subjective rules give subjective findings.
- The noise on a clean PR is not solved, and ambiguity detection still needs a design of its own (a separate pass).
- Unauthenticated GitHub access is limited to 60 requests an hour: a day of demos exhausts it. Set a read-only `GITHUB_TOKEN`, or
  review saved snapshots (`review-agent review <snapshot folder>`), which are also exact and reproducible.

## 9. Repository context and the three-configuration comparison (details in `evaluation/results/context-ablation/README.md`)

- Added a lightweight code graph (`codegraph.py`): for each changed Python function, its callers, callees, tests and class constructor, found
  with `ast`, from one repository download (2 requests), saved with the snapshot, shown to every pass and the verifier.
- Comparison on the six demo PRs, one run each: LLM only, + Ruff/Bandit, + repository context. **All three found all four planted
  defects and got the same checklists right**: the planted defects are visible in the diff, so the extra layers had nothing to add (ceiling effect).
- Tools gave deterministic backing (not dismissable by the verifier) rather than more recall. Context used about 14% more input tokens and showed
  no verifier dismissals (3 and 5 in the other configurations): a lead, not a result, with one run each.
- Real lesson on method: trying the new module on real branches before any model run found two bugs that would have fed false facts to the model, and
  replaying 18 saved runs showed a merge rule that was too greedy. Offline replay of saved runs is a cheap way to test the deterministic parts.
- To test context properly we need pull requests whose defect is only visible with the surrounding code. Not built yet.
