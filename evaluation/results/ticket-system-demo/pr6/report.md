# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#6, head `41791e15375771ff4d2504ca8e5d5069f947a340`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/6)
- **Case:** ebirdyx-ticket-system-demo-pr6-41791e1
- **Ticket:** TS-6: Due dates and overdue tickets
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v2
- **Date (UTC):** 2026-10-13T23:06:45+00:00
- **Model time:** 24.9 s; tokens: 30710 in / 6346 out
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
| compliance | ok | 4.0 s | 6551 / 927 | 0 candidate finding(s) |
| defects | ok | 9.1 s | 6103 / 2396 | 2 candidate finding(s) |
| security | ok | 3.2 s | 6037 / 680 | 0 candidate finding(s) |
| standards | ok | 4.1 s | 5975 / 1187 | 2 candidate finding(s) |
| verify | ok | 5.1 s | 6044 / 1156 | 2 dismissed |

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

> The service implements an overdue method that returns tickets with a past due date and not closed, and a test verifies that overdue tickets are correctly listed.

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

### 1. [LOW] Rule: public functions must have a docstring that describes what they return or raise

- **Category:** maintainability
- **Location:** `tickets/service.py:43`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The public method `set_due_date` has a one‑line docstring that does not mention its return value or possible exceptions, contrary to the documented rule.)

> The newly added public method `set_due_date` has a one‑line docstring, but it does not mention the return value or any exceptions, violating the team rule that public functions' docstrings must state what they return or raise.

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
3. Public functions have type hints and a one-line docstring that says what they return or raise.
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

## Dismissed by verification

These candidates were judged unsupported by the verification pass. They are listed so nothing disappears silently; the human reviewer can overrule the verifier.

- **Overdue method includes RESOLVED tickets** (`tickets/service.py:50`, found by defects): The overdue method intentionally includes RESOLVED tickets as per its docstring, and the ticket criteria do not require excluding them.
- **Duplicate import of `date` in test module** (`tests/test_service.py:1`, found by defects): The diff adds a single import of `date`; there is no existing identical import, so no duplicate import exists.
