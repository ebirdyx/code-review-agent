# Three configurations on the six demo pull requests

Date: 2026-10-14. Same six pull requests of `ebirdyx/ticket-system-demo`, same saved snapshots, same free model
(`gpt-oss:120b`), prompt set `multi_v4`, one run each. Answer key: `demo/ticket-system/README.md` (written before any run).

| Config | What it is | Flags |
|---|---|---|
| **A** | LLM only | `--no-context --no-tools` |
| **B** | LLM + static tools (Ruff, Bandit) | `--no-context` |
| **C** | LLM + static tools + repository context (callers, callees, tests, class) | (default) |

Results are in `A/`, `B/`, `C/` (`prN/result.json` and `report.md`); the table below is produced by
`evaluation/score_context_ablation.py` from those files. **Six pull requests, one run each, one non-deterministic model:
this is an illustration, not a statistical result.** Differences of one or two findings are inside the run-to-run noise we
saw between earlier runs of the same configuration.

## Results

| | A: LLM only | B: + tools | C: + tools + context |
|---|--:|--:|--:|
| Planted defects found (4 pull requests have one) | 4 / 4 | 4 / 4 | 4 / 4 |
| Requirement checklists correct (6 pull requests) | 5 / 6 | 5 / 6 | 5 / 6 |
| Findings kept (all six PRs) | 10 | 9 | 10 |
| ...of which the planted defect | 4 | 4 | 4 |
| ...valid minor remarks (hand-judged) | 1 | 2 | 2 |
| ...duplicates of a planted defect (hand-judged) | 1 | 0 | 1 |
| ...debatable or wrong remarks (hand-judged) | 4 | 3 | 3 |
| Candidates dismissed by the verifier | 3 | 5 | 0 |
| Input tokens, all six PRs | 154 116 | 156 781 | 175 812 |
| Model time, all six PRs | 100.6 s | 91.9 s | 88.9 s |

The hand judgement is mine (one reader, not a blinded labeller): "valid minor" = a true but small observation (a missing
boundary test, a public method with no docstring); "debatable or wrong" = mostly docstring remarks about docstrings that
do say what is raised or returned, plus one arguable "foreign keys are not enforced"; "duplicate" = the same defect reported
again as a separate finding.

## What this shows, and what it does not

1. **Detection did not change.** All three configurations found all four planted defects and got the same checklists
   right. These defects are visible in the diff itself, so there was nothing for tools or context to add. This is a
   ceiling effect of easy synthetic cases, not proof that the extra layers are useless.
2. **The static tools did what they are for, not more.** In B and C the SQL injection and the swallowed exception are
   backed by a deterministic finding (Bandit B608, Ruff BLE001, Bandit B110) that the verifier cannot dismiss. In A the
   model found the same defects alone. The tools add certainty and a second opinion, not recall, on this sample.
3. **Context may reduce speculation, but one run each cannot tell.** C produced no candidate that the verifier had to
   dismiss (A: 3, B: 5), which could mean the model hedges less when it sees the surrounding code, but we did not check why. The earlier runs of the same configuration varied by about
   that much, so this is a lead to test, not a finding.
4. **Context costs about 14% more input tokens** than B (the related code and facts are sent to every pass and the verifier),
   and no more model time in these runs.
5. **Nothing here detects the vague requirement (PR 6)** in any configuration: "Overdue tickets are flagged" is marked MET each time.
6. **One new duplicate in C (PR 5):** the same swallowed exception is reported at line 45 (tool-backed) and line 42 (model,
   three lines away). Near-line merging only exists for criterion findings, so the two stay separate.

## How the feature should be tested properly

The demo pull requests cannot show the value of repository context, because every planted defect is in the diff. A fair test
needs pull requests whose defect is visible only with the surrounding code, for example a change to a function's return value,
exception or argument order that a caller or a test relies on, or a "fix" that makes an existing test meaningless. That test was
then done: see `../context-dependent/README.md` (2 of 9 found without context, 9 of 9 with it).
