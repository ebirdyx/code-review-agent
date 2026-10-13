# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#2, head `2ad2b01eaa423cc125af1ff5b0df8781230c15a0`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/2)
- **Case:** ebirdyx-ticket-system-demo-pr2-2ad2b01
- **Ticket:** TS-2: Escalate stale tickets
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v3
- **Date (UTC):** 2026-10-13T23:52:52+00:00
- **Model time:** 11.9 s; tokens: 23921 in / 4692 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 2 findings

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

2 file(s) changed, +53 / -0 lines (1 source, 1 test); file types: .py x2.

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 2 | 0 | 0 |  |
| bandit 1.9.4 | ok | 2 | 0 | 0 | 12 warning(s) in test files were ignored (noise in tests) |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 3.6 s | 5250 / 1506 | 1 candidate finding(s) |
| defects | ok | 2.4 s | 4645 / 672 | 1 candidate finding(s) |
| security | ok | 2.1 s | 4579 / 787 | 1 candidate finding(s) |
| standards | ok | 2.8 s | 4652 / 1115 | 1 candidate finding(s) |
| verify | ok | 1.7 s | 4795 / 612 | 1 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. NOT MET: An open ticket that has existed for 48 hours or more is raised by one priority level.

> The ticket requires escalation for tickets that have existed for 48 hours **or more**, but the implementation uses a strict greater‑than comparison (`> ESCALATION_AGE`). Tickets exactly 48 hours old will not be escalated, violating the acceptance criterion.

From ticket:

```
1. An open ticket that has existed for 48 hours or more is raised by one priority level.
```

From code:

```
if now - ticket.created_at > ESCALATION_AGE:
```

Where: `tickets/service.py:50`

### 2. MET: An urgent ticket stays urgent.

> Urgent tickets have the highest priority in `PRIORITY_ORDER`. The code only increments priority when the current index is less than the last index, so an urgent ticket (last in the list) is never raised to a higher level.

From ticket:

```
2. An urgent ticket stays urgent.
```

From code:

```
if index < len(PRIORITY_ORDER) - 1:
    ticket.priority = PRIORITY_ORDER[index + 1]
```

From code:

```
assert service.escalate_stale(NOW) == []
assert service.get(ticket.id).priority is Priority.URGENT
```

Where: `tickets/service.py:51`

### 3. MET: Tickets that are not open (in progress, resolved, closed) are never escalated.

> The escalation routine iterates only over tickets returned by `self.store.list_by_status(Status.OPEN)`, so tickets that are not open are never considered for escalation.

From ticket:

```
3. Tickets that are not open (in progress, resolved, closed) are never escalated.
```

From code:

```
for ticket in self.store.list_by_status(Status.OPEN):
```

From code:

```
service.change_status(ticket.id, Status.IN_PROGRESS)
assert service.escalate_stale(NOW) == []
```

Where: `tickets/service.py:49`

## Findings

### 1. [MEDIUM] Escalation condition excludes tickets exactly 48 hours old

- **Category:** boundary_condition
- **Location:** `tickets/service.py:50`
- **Location and quotes:** checked against the input
- **Found by:** compliance, defects
- **Verification:** supported (The code uses `if now - ticket.created_at > ESCALATION_AGE:` which excludes tickets exactly 48 hours old, while the acceptance criteria require escalation for tickets "48 hours or more".)

> The code uses a strict greater-than comparison (`now - ticket.created_at > ESCALATION_AGE`) to decide whether a ticket should be escalated. The acceptance criteria require tickets that are "48 hours or more" old to be escalated, so tickets that are exactly 48 hours old are incorrectly left unchanged. This off‑by‑one boundary can cause tickets to miss the required priority increase. Also reported by compliance as requirement_mismatch: The ticket requires escalation for tickets that have existed for 48 hours **or more**, but the implementation uses a strict greater‑than comparison (`> ESCALATION_AGE`). Tickets exactly 48 hours old will not be escalated, violating the acceptance criterion.

**Evidence**

From code:

```
ESCALATION_AGE = timedelta(hours=48)
```

From code:

```
if now - ticket.created_at > ESCALATION_AGE:
```

From ticket:

```
1. An open ticket that has existed for 48 hours or more is raised by one priority level.
```

### 2. [LOW] Rule: test boundary value missing

- **Category:** maintainability
- **Location:** `tests/test_service.py:64`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The team rule requires tests for boundary values (e.g., exactly 48 hours), but the added test suite lacks a test for the exact 48‑hour boundary.)

> The new behavior escalates tickets older than 48 hours, but the added tests do not include a test for the exact boundary value of 48 hours, violating the rule that every change in behaviour must be tested at its boundary values.

**Evidence**

From code:

```
def test_an_old_open_ticket_is_escalated_one_level(service):
    ticket = aged(service, 72)
    assert [t.id for t in service.escalate_stale(NOW)] == [ticket.id]
    assert service.get(ticket.id).priority is Priority.HIGH
```

From rules:

```
Every change in behaviour comes with a test, including the boundary values (for example "exactly 48 hours").
```

_1 duplicate finding(s) merged into another finding._

## Dismissed by verification

These candidates were judged unsupported by the verification pass. They are listed so nothing disappears silently; the human reviewer can overrule the verifier.

- **Missing authorization check for priority escalation** (`tickets/service.py:45`, found by security): No team rule or requirement mandates an authorization check for priority escalation, so the claim of a missing permission check is not substantiated by the provided material.
