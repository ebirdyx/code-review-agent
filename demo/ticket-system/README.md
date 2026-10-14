# ticket-system-demo: the demonstration project

Repository reviewed: https://github.com/ebirdyx/ticket-system-demo (synthetic Python ticket tracker, written for this
course project; not the team members' private `ticket-system`). It has six open pull requests, each with a
Jira-style ticket stored here in `tickets/TS-n.json` (the tickets are **not** in a real Jira; use `--ticket`).

Review one PR:

```powershell
uv run review-agent review-pr ebirdyx/ticket-system-demo#2 --ticket demo/ticket-system/tickets/TS-2.json
```

## What each pull request contains (the answer key, written BEFORE running the agent)

| PR | Ticket | Planted problem | Expected |
|---|---|---|---|
| #1 | TS-1 comments | none (clean change with tests) | no real finding; all criteria MET |
| #2 | TS-2 escalate stale tickets | `now - created_at > 48 h` should be `>= 48 h`; tests do not cover exactly 48 hours | boundary defect at `service.py`, criterion 1 NOT MET |
| #3 | TS-3 search by assignee | SQL built with an f-string (injection); breaks the team rule on bound parameters | security finding (Bandit B608 should also fire) |
| #4 | TS-4 who can resolve | the reporter is allowed and administrators are ignored (`admins` parameter unused) | criteria 1 and 2 NOT MET |
| #5 | TS-5 notify on assignment | `except Exception: pass` hides the failure and nothing is logged | criterion 3 NOT MET; team rule on silent exceptions |
| #6 | TS-6 due dates | requirement is vague: is "due today" overdue? are resolved tickets overdue? what time zone? | the agent should say it cannot determine, not invent a rule |

The team rules the agent reads from the base branch are in the demo repository's `.review-agent/rules.md`.

## Honest limits

- The defects are planted by us, in a small project: this shows the tool working on realistic pull requests, it does not
  measure accuracy. One run per model per pull request.
- Results of each run are saved in `evaluation/results/ticket-system-demo/` (report, JSON result, comment text).

## Context-dependent pull requests (PRs 7 to 9): the defect is NOT in the diff

Added to test the repository-context feature. Answer key written **before** any run. In each case the diff alone looks
reasonable; the problem is in code the pull request does not touch (a caller, or existing tests). Each of these pull
requests leaves the existing tests of `main` failing, as a real incomplete change would.

| PR | Ticket | What the diff changes | The problem, outside the diff | Expected finding |
|---|---|---|---|---|
| #7 | TS-7 store raises on unknown id | `TicketStore.get` raises `KeyError` instead of returning `None` | `TicketService.get` still tests `if ticket is None` and raises `TicketNotFound`; now a `KeyError` leaks out and `test_unknown_ticket` fails | mentions the caller (`service.get` / `TicketNotFound` / the `None` check) |
| #8 | TS-8 transition returns a copy | `workflow.transition` returns an updated copy and no longer mutates its argument | `TicketService.change_status` ignores the return value, so a ticket's status never changes; `test_status_follows_the_workflow` fails | mentions `change_status` or the ignored return value |
| #9 | TS-9 keep titles as typed | `create_ticket` no longer calls `title.strip()` | the emptiness check relies on it, so whitespace-only titles are now accepted; two existing tests assert stripping and fail | mentions whitespace-only titles or the existing tests that expect stripping |

How it will be run: configurations B (static tools, no repository context) and C (tools plus context), three runs each,
on identical saved snapshots. "Found" is judged by reading the finding, not only by keywords. Six runs per pull request is
still a tiny sample, so the result is an indication.
