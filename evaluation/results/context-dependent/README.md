# Context-dependent pull requests: with and without repository context

Date: 2026-10-14. Pull requests 7, 8 and 9 of `ebirdyx/ticket-system-demo`, whose problem is **outside the diff** (a caller that
still expects the old behaviour, or existing tests that no longer match). Answer key written before any run:
`demo/ticket-system/README.md`, section "Context-dependent pull requests". Same free model (`gpt-oss:120b`), same saved
snapshots (`snapshots/`), prompt set `multi_v4`, static tools on in both configurations.

| Config | Repository context | Runs |
|---|---|--:|
| **B** | off (`--no-context`) | 3 per pull request |
| **C** | on (default) | 3 per pull request |

Raw results: `B/rN/prM/` and `C/rN/prM/` (`result.json`, `report.md`). `snapshots/prM/related.json` shows the callers, callees and tests
the code graph found.

Each existing test suite of `main` fails on these branches exactly as the key predicts (`test_unknown_ticket` on PR 7,
`test_status_follows_the_workflow` on PR 8, two title tests on PR 9), so the defects are real.

## Was the planted problem found? (my reading of each finding)

| PR | The problem outside the diff | B, no context (3 runs) | C, with context (3 runs) |
|---|---|---|---|
| #7 | `TicketService.get` still expects `None` from the store | missed, missed, missed (no finding at all) | found (names `service.get` and `TicketNotFound`), found (callers named, but framed as a security leak), found (names the caller and the failing tests) |
| #8 | `change_status` ignores the value `transition` now returns | missed (no finding), missed (an unrelated speculative `KeyError`), missed (same) | found, found, found (each: "service layer ignores the returned ticket", HIGH) |
| #9 | whitespace-only titles accepted; existing tests expect stripping | found (medium), missed (found, then dismissed by the verifier), found (low, framed as injection risk) | found (only the stale test), found (whitespace and stale tests, plus a speculative XSS claim), found (whitespace, medium) |
| **Total** | | **2 of 9** | **9 of 9** |

PRs 7 and 8 are the clean test, because nothing in their diff shows the problem: 0 of 6 without context, 6 of 6 with it. PR 9
is partly visible in the diff, and the gap there is small (2 of 3 against 3 of 3).

## What this shows

1. **Repository context made the difference exactly where it should.** When the defect is in a caller that the diff does not
   show, the model without context did not find it (it also invented unrelated worries on PR 8); with the caller and the tests in
   front of it, it found it every time and named the right function. This is the first real evidence for the feature.
2. **When the defect is visible in the diff, context adds little** (PR 9, and the six earlier demo pull requests).
3. **It is not free of noise.** Speculative findings still appear with context (a stored-XSS worry on PR 9, a "leaks the ticket id"
   framing on PR 7), and the docstring remarks from the rules pass appear in both configurations.

## Limits (state these in the report)

- **I designed these three cases** after the feature existed, to test it, and chose defects that need context. They show the
  feature works when it is needed; they do not show how often real pull requests need it.
- **Three pull requests, three runs each, one model, one reader** (my reading, not a blinded labeller). Counts are small.
- The code graph found the right caller or tests every time here, in a repository of a few files with names that are easy to
  match. On a large repository with many functions of the same name, name matching will be less precise.
- One "found" (PR 7, run C2) is weaker than the others: right content, but framed as a security issue and located in the store,
  not in the caller.
