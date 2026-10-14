# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#6, head `41791e15375771ff4d2504ca8e5d5069f947a340`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/6)
- **Case:** ebirdyx-ticket-system-demo-pr6-41791e1
- **Ticket:** TS-6: Due dates and overdue tickets
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T01:49:47+00:00
- **Model time:** 14.8 s; tokens: 31564 in / 4826 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 1 finding

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
| compliance | ok | 4.2 s | 6847 / 1252 | 0 candidate finding(s) |
| defects | ok | 5.2 s | 6242 / 1489 | 0 candidate finding(s) |
| security | ok | 2.9 s | 6176 / 726 | 0 candidate finding(s) |
| standards | ok | 2.0 s | 6249 / 977 | 2 candidate finding(s) |
| verify | ok | 1.2 s | 6050 / 382 | 0 dismissed |

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

Where: `tickets/models.py:34`

### 2. MET: Overdue tickets are flagged.

> The service implements an overdue method that returns tickets whose due date is before today and are not closed, and a test verifies that overdue tickets are listed, satisfying the flagging requirement.

From code:

```
def overdue(self, today: date | None = None) -> list[Ticket]:
```

From code:

```
if t.due_date is not None and t.due_date < today
```

Where: `tickets/service.py:50`

## Findings

### 1. [LOW] Rule: public functions must have docstring stating return

- **Category:** maintainability
- **Location:** `tickets/service.py:43`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The public method `set_due_date` has a one‑line docstring that does not mention its return value, violating the rule that public functions must have a docstring stating what they return or raise.)

> The newly added public function `set_due_date` has a one-line docstring, but it does not describe what the function returns, violating the rule that public functions must have a docstring that says what they return or raise.

**Evidence**

From code:

```
def set_due_date(self, ticket_id: int, due: date | None) -> Ticket:
    """Set or clear the due date of a ticket."""
    ticket = self.get(ticket_id)
    ticket.due_date = due
    self.store.save(ticket)
    return ticket
```

From rules:

```
Public functions have type hints and a one-line docstring that says what they return or raise.
```

From code:

```
def overdue(self, today: date | None = None) -> list[Ticket]:
    """Tickets whose due date has passed and that are not closed."""
    today = today or date.today()
    return [
        t for status in (Status.OPEN, Status.IN_PROGRESS, Status.RESOLVED)
        for t in self.store.list_by_status(status)
        if t.due_date is not None and t.due_date < today
    ]
```

_1 duplicate finding(s) merged into another finding._

## Limitations stated by the model

- The acceptance criteria and business rules for whether RESOLVED tickets should be considered overdue are not provided, so I cannot determine if including them in the overdue list is a defect.
- The review scope is limited to security; broader security context such as authentication and authorization mechanisms is not visible in the provided code.
