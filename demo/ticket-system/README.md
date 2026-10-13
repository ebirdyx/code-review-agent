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
