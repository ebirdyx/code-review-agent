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

---

# Second run: after the improvements (`multi_v3` prompts, cross-category merging, consistency check)

Same six pull requests, same free model (`gpt-oss:120b`), one run each, results in `../ticket-system-demo-v3/`. PRs 1 to 3 were
fetched from GitHub; PRs 4 to 6 were reviewed from their saved snapshots because the unauthenticated GitHub limit
(60 requests an hour) had been used up. A single run per PR with a non-deterministic model: **differences of one or two
findings are noise, not proof.**

| PR | Findings before -> after | What changed |
|---|---|---|
| #1 clean | 2 -> 3 | still no real defect, but now 1 debatable MEDIUM ("the store does not check the ticket exists", while the service does) plus 2 docstring remarks that are wrong (the docstrings do say what they raise or return). Not better. |
| #2 escalation | 2 -> 2 | the bug is found again (compliance + defects); severity came out MEDIUM this time instead of HIGH |
| #3 SQL | 4 -> 3 | the injection is now **one** finding listing Bandit, security and rules as sources (it was 3 separate findings). The other two are a plausible whitespace issue and a true "no docstring" remark |
| #4 resolve | 3 -> 3 | the permission defect is now one HIGH finding from compliance + defects + security (it was 3); one extra LOW (unused `admins` parameter, true) and one docstring remark |
| #5 notify | 4 -> 1 | everything about the swallowed exception is one finding from Ruff, Bandit, compliance, defects and rules; the docstring noise did not come back |
| #6 due dates | 1 -> 0 | the docstring noise is gone, **but the ambiguity is still not detected** |

## What the improvements did

- **Merging works, and it is deterministic.** Replaying the six saved first-run results through the new assembly code (no model call) gave
  4 -> 2 findings on #3, 3 -> 2 on #4, 4 -> 2 on #5. The live second run shows the same shape. No explanation is lost: a different
  angle is appended as "Also reported by ... as <category>: ...".
- **Consistency check:** it stayed silent on the other five runs (where no finding contradicted a MET verdict), which is intended; it fired once, on #3
  (a plausible-looking whitespace finding sits on the code that satisfies criterion 1), where it is an informative pointer, not an error. It was
  designed from the two Qwen runs, where the checklist said MET on a line a finding blamed (unit-tested with that case); it has not been run live
  against a model that makes that mistake.
- **Prompt-only changes helped little with this model.** The stricter rules text removed the docstring noise on #5 and #6 but not on #1 and
  #4, even though the prompt now contains the exact example ("Comments of a ticket, oldest first." satisfies the rule). The "vague criteria" guidance did
  not make the model say "cannot determine" on #6. A prompt cannot force a model's judgement.

## Open items this run leaves

1. **Ambiguity detection (PR #6) is still missing.** Idea: a small dedicated pass that reads only the acceptance criteria and lists the
   questions a developer would have to ask (undefined words, unstated boundaries), shown as "open questions" next to the checklist.
2. **Subjective team rules produce subjective findings.** The demo rule "a docstring that says what they return or raise" is hard to apply. Write
   rules that can be checked objectively ("every public function has a docstring"), or accept some noise from this pass.
3. **Noise on the clean PR is not solved** (3 findings, none a real defect).
4. **Everything is one run per PR.** To say anything statistical we need repeated runs (`--repeat`) on the benchmark.
