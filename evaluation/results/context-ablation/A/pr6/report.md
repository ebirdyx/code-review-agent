# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#6, head `41791e15375771ff4d2504ca8e5d5069f947a340`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/6)
- **Case:** ebirdyx-ticket-system-demo-pr6-41791e1
- **Ticket:** TS-6: Due dates and overdue tickets
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T01:51:52+00:00
- **Model time:** 21.4 s; tokens: 30949 in / 5838 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 1 finding

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

4 file(s) changed, +48 / -8 lines (3 source, 1 test); file types: .py x4.

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 4.8 s | 6740 / 1629 | 0 candidate finding(s) |
| defects | ok | 8.1 s | 6135 / 1785 | 0 candidate finding(s) |
| security | ok | 4.4 s | 6069 / 1024 | 0 candidate finding(s) |
| standards | ok | 3.5 s | 6142 / 1013 | 2 candidate finding(s) |
| verify | ok | 1.4 s | 5863 / 387 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: A ticket can have an optional due date.

> The Ticket model includes an optional due_date field and the service provides set_due_date to set or clear it, satisfying the requirement for an optional due date.

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
"""Set or clear the due date of a ticket."""
```

Where: `tickets/models.py:34`

### 2. MET: Overdue tickets are flagged.

> The service implements an overdue method that returns tickets whose due date has passed and are not closed, and a test confirms overdue tickets are correctly listed.

From code:

```
def overdue(self, today: date | None = None) -> list[Ticket]:
```

From code:

```
"""Tickets whose due date has passed and that are not closed."""
```

From code:

```
if t.due_date is not None and t.due_date < today
```

Where: `tickets/service.py:50`

## Findings

### 1. [LOW] Rule: Public functions must have a docstring that says what they return or raise

- **Category:** maintainability
- **Location:** `tickets/service.py:44`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The public method `set_due_date` has a one‑line docstring that does not mention its return value or possible exceptions, violating the rule that docstrings must state what the function returns or raises.)

> The public method `set_due_date` has a one-line docstring, but it does not describe what the function returns or raises, violating the team rule requiring such documentation.

**Evidence**

From code:

```
"""Set or clear the due date of a ticket."""
```

From rules:

```
Public functions have type hints and a one-line docstring that says what they return or raise.
```

From code:

```
"""Tickets whose due date has passed and that are not closed."""
```

_1 duplicate finding(s) merged into another finding._

## Limitations stated by the model

- Cannot assess whether permission/authorization checks are required for the new set_due_date and overdue methods, as the surrounding authentication/authorization context is not provided.
