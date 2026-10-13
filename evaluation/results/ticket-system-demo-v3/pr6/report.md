# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#6, head `41791e15375771ff4d2504ca8e5d5069f947a340`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/6)
- **Case:** ebirdyx-ticket-system-demo-pr6-41791e1
- **Ticket:** TS-6: Due dates and overdue tickets
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v3
- **Date (UTC):** 2026-10-13T23:55:21+00:00
- **Model time:** 17.1 s; tokens: 30864 in / 6083 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 0 findings

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

4 file(s) changed, +48 / -8 lines (3 source, 1 test); file types: .py x4.

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 4 | 0 | 0 |  |
| bandit 1.9.4 | ok | 4 | 0 | 0 | 9 warning(s) in test files were ignored (noise in tests) |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 1.9 s | 6708 / 800 | 0 candidate finding(s) |
| defects | ok | 6.0 s | 6103 / 1874 | 0 candidate finding(s) |
| security | ok | 4.1 s | 6037 / 1399 | 1 candidate finding(s) |
| standards | ok | 2.2 s | 6110 / 953 | 1 candidate finding(s) |
| verify | ok | 3.4 s | 5906 / 1057 | 1 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: A ticket can have an optional due date.

> The Ticket model includes an optional due_date field and the service provides set_due_date to set or clear it, satisfying the optional due date requirement.

From code:

```
due_date: date | None = None
```

From code:

```
def set_due_date(self, ticket_id: int, due: date | None) -> Ticket:
```

From code:

```
assert service.set_due_date(ticket.id, date(2026, 11, 1)).due_date == date(2026, 11, 1)
```

From code:

```
assert service.set_due_date(ticket.id, None).due_date is None
```

Where: `tickets/models.py:34`

### 2. MET: Overdue tickets are flagged.

> The service provides an overdue method that returns tickets whose due date has passed and are not closed, and a test confirms overdue tickets are listed.

From code:

```
def overdue(self, today: date | None = None) -> list[Ticket]:
```

From code:

```
if t.due_date is not None and t.due_date < today
```

From code:

```
assert [t.id for t in service.overdue(date(2026, 10, 13))] == [late.id]
```

Where: `tickets/service.py:50`

## Findings

No findings were reported. This is the model's claim, not a guarantee that the change is correct.

_1 duplicate finding(s) merged into another finding._

## Dismissed by verification

These candidates were judged unsupported by the verification pass. They are listed so nothing disappears silently; the human reviewer can overrule the verifier.

- **Missing authorization check for setting ticket due date** (`tickets/service.py:43`, found by security, standards): The claim of a missing authorization check is not evidenced in the provided code, while the docstring issue is valid but the finding conflates two separate problems, making the overall claim unsupported
