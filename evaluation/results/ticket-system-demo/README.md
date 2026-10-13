# Results: the agent on `ebirdyx/ticket-system-demo` (six pull requests)

Run on 2026-10-13 with the default free model (`gpt-oss:120b`, Ollama Cloud), multi-pass pipeline `multi_v2`, static analysis
(Ruff, Bandit) and the team rules read from the base branch. One run per pull request. The answer key was written in
`demo/ticket-system/README.md` **before** the runs. Each folder here holds the report, the validated result, the comment text
that would be posted, the exact context sent to the model, the raw answers of every pass and the event log.

This is a demonstration on a small project whose defects we planted ourselves. It is **not** a measure of accuracy.

## Scorecard against the answer key

| PR | Planted problem | Found? | How | Checklist | Noise |
|---|---|---|---|---|---|
| #1 comments (clean) | none | n/a, no real defect reported | | 4/4 MET (correct) | 2 LOW "docstring" findings from the rules pass, both debatable (the docstrings do say what is returned) |
| #2 escalation | `>` instead of `>=` at 48 h | **yes**, HIGH | compliance + defects, verified; the rules pass also noted the missing exact-48 h test | criterion 1 NOT MET (correct) | none |
| #3 search by assignee | SQL injection (f-string) | **yes** | Bandit B608 + security + defects + rules; verified | all MET (correct: the ticket never asks for injection safety) | same defect reported 3 times, plus 1 docstring finding |
| #4 who can resolve | reporter allowed, admins ignored | **yes**, HIGH | compliance + defects + security, verified | criterion 1 NOT MET (correct) | same defect reported 3 times |
| #5 notify on assignment | silent `except Exception: pass`, no logging | **yes** | Ruff BLE001 + Bandit B110 + compliance + defects + rules; verified | criterion 3 NOT MET (correct) | 1 docstring finding |
| #6 due dates | vague requirement | **no** | the agent did not say it could not decide what "overdue" means | both MET | 1 docstring finding |

Summary: 4 of 4 planted defects found, the three requirement checklists that had a violation were right, the clean PR
produced no substantive false alarm. The verifier dismissed 5 candidates over the six runs. Three were rightly dropped (an
invented "indentation error", a "duplicate import" that does not exist, a speculative "missing authorization check"), the
first time it clearly helped. One is arguable (PR #6: "overdue includes resolved tickets", dismissed because the ticket does
not say otherwise: this is exactly the ambiguity nobody pointed out). One was dismissed for a wrong reason (PR #4: a rules
finding, "outside the verifier's scope"), a quirk of the verifier prompt that should not judge rule findings at all.

## What did not work well (to fix or to state in the report)

1. **Ambiguity not detected (PR #6).** The agent marked "Overdue tickets are flagged" as MET and never said that "overdue"
   is undefined (due today? resolved tickets? time zone?). A good reviewer would ask.
2. **The same root cause is reported several times** when passes use different categories (PR #3 and #4: 3 findings for one
   defect). Findings on the same line are only merged when their categories are compatible. Known limitation.
3. **The rules pass is pedantic.** Rule 3 of the demo rules ("a docstring that says what it returns or raises") produced a
   LOW finding on five of six PRs, some of them wrong, and the verifier confirmed them. Either the rule is too subjective or
   the pass should be stricter about what counts as a violation.
4. **A bug found by running it for real:** four of the six runs crashed after the model had answered, because printing the
   report to a redirected Windows output failed on a non-breaking hyphen (U+2011) written by the model. Fixed (output now
   replaces what it cannot show) with a regression test.

## Reproduce

```powershell
uv run review-agent review-pr ebirdyx/ticket-system-demo#2 --ticket demo/ticket-system/tickets/TS-2.json
```

(Pull requests, branches and the demo repository must still exist; results will differ from run to run, the model is not deterministic.)
