# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#6, head `41791e15375771ff4d2504ca8e5d5069f947a340`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/6)
- **Case:** ebirdyx-ticket-system-demo-pr6-41791e1
- **Ticket:** TS-6: Due dates and overdue tickets
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T01:47:32+00:00
- **Model time:** 15.4 s; tokens: 38486 in / 5027 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 1 finding

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

4 file(s) changed, +48 / -8 lines (3 source, 1 test); file types: .py x4.

## Repository context

Code outside the change that the model was shown, found by matching function names (it can match the wrong function).

- `TicketService.overdue` (tickets/service.py) is called by 0 other repository function(s) and mentioned in 1 test function(s) (1 added or changed by this change).
- `TicketService.set_due_date` (tickets/service.py) is called by 0 other repository function(s) and mentioned in 2 test function(s) (2 added or changed by this change).
- `TicketStore.save` (tickets/store.py) is called by 3 other repository function(s) and mentioned in 1 test function(s).
- `TicketStore.add` (tickets/store.py) is called by 1 other repository function(s) and mentioned in 3 test function(s).
- `_from_row` (tickets/store.py) is called by 3 other repository function(s) and mentioned in no test function.
- caller of `TicketStore.save`: tickets/service.py:37-41 (`TicketService.assign`)
- caller of `TicketStore.add`: tickets/service.py:22-29 (`TicketService.create_ticket`)
- caller of `_from_row`: tickets/store.py:43-45 (`TicketStore.get`)
- test of `TicketStore.save`: tests/test_store.py:16-22 (`test_list_by_status`)
- test of `TicketStore.add`: tests/test_store.py:9-13 (`test_add_and_get_round_trip`)
- class of `TicketService.overdue`: tickets/service.py:19-20 (`TicketService.__init__`)
- class of `TicketStore.save`: tickets/store.py:26-29 (`TicketStore.__init__`)
- callee of `TicketService.overdue`: tickets/store.py:56-58 (`TicketStore.list_by_status`)
- callee of `TicketService.set_due_date`: tickets/service.py:31-35 (`TicketService.get`)
- caller of `TicketStore.save`: tickets/service.py:59-63 (`TicketService.change_status`)
- caller of `_from_row`: tickets/store.py:60-64 (`TicketStore.search_title`)
- test of `TicketStore.add`: tests/test_store.py:25-30 (`test_search_title_is_a_substring_match_and_safe_with_quotes`)

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 4 | 0 | 0 |  |
| bandit 1.9.4 | ok | 4 | 0 | 0 | 9 warning(s) in test files were ignored (noise in tests) |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 2.9 s | 8229 / 715 | 0 candidate finding(s) |
| defects | ok | 5.0 s | 7624 / 1615 | 0 candidate finding(s) |
| security | ok | 3.6 s | 7558 / 991 | 0 candidate finding(s) |
| standards | ok | 3.4 s | 7631 / 1285 | 2 candidate finding(s) |
| verify | ok | 1.3 s | 7444 / 421 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: A ticket can have an optional due date.

> The Ticket model includes an optional due_date field and the service provides a method to set or clear it, satisfying the optional due date requirement.

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

> The overdue method returns tickets whose due date has passed and are not closed, and a test verifies that overdue tickets are correctly listed.

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

### 1. [LOW] Rule: public functions must have docstring describing return or raise

- **Category:** maintainability
- **Location:** `tickets/service.py:43`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The public method `set_due_date` has a one-line docstring that does not mention its return value or possible exceptions, violating rule 3 which requires such a docstring.)

> The public method `set_due_date` has a one-line docstring that does not state what the function returns or raises, violating the rule that public functions must have a docstring describing their return value or raised exceptions.

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

- The code does not include tests for the boundary condition where a ticket's due_date is exactly equal to the 'today' parameter; cannot assess if this edge case is handled correctly.
- The review does not include any information about authentication or authorization mechanisms surrounding the TicketService methods, so potential missing permission checks cannot be fully assessed.
