# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#2, head `2ad2b01eaa423cc125af1ff5b0df8781230c15a0`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/2)
- **Case:** ebirdyx-ticket-system-demo-pr2-2ad2b01
- **Ticket:** TS-2: Escalate stale tickets
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v2
- **Date (UTC):** 2026-10-13T23:05:46+00:00
- **Model time:** 22.8 s; tokens: 23607 in / 5488 out
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
| compliance | ok | 5.3 s | 5093 / 1313 | 1 candidate finding(s) |
| defects | ok | 3.6 s | 4645 / 749 | 1 candidate finding(s) |
| security | ok | 4.6 s | 4579 / 959 | 1 candidate finding(s) |
| standards | ok | 6.7 s | 4517 / 1679 | 1 candidate finding(s) |
| verify | ok | 3.3 s | 4773 / 788 | 1 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. NOT MET: An open ticket that has existed for 48 hours or more is raised by one priority level.

> The code uses a strict greater-than comparison (`> ESCALATION_AGE`) which excludes tickets that are exactly 48 hours old, while the criterion requires escalation for tickets that have existed for 48 hours or more (>= 48 hours).

From code:

```
if now - ticket.created_at > ESCALATION_AGE:
```

From ticket:

```
1. An open ticket that has existed for 48 hours or more is raised by one priority level.
```

Where: `tickets/service.py:50`

### 2. MET: An urgent ticket stays urgent.

> Urgent tickets have the highest priority in `PRIORITY_ORDER`; the index check prevents increasing priority beyond the last element, so urgent tickets remain urgent.

From code:

```
index = PRIORITY_ORDER.index(ticket.priority)
if index < len(PRIORITY_ORDER) - 1:
    ticket.priority = PRIORITY_ORDER[index + 1]
```

Where: `tickets/service.py:51`

### 3. MET: Tickets that are not open (in progress, resolved, closed) are never escalated.

> The escalation loop only iterates over tickets with status `Status.OPEN`, so tickets that are not open are never considered for escalation.

From code:

```
for ticket in self.store.list_by_status(Status.OPEN):
```

Where: `tickets/service.py:49`

## Findings

### 1. [HIGH] Escalation condition excludes tickets exactly 48 hours old

- **Category:** boundary_condition
- **Location:** `tickets/service.py:50`
- **Location and quotes:** checked against the input
- **Found by:** compliance, defects
- **Verification:** supported (The implementation uses `if now - ticket.created_at > ESCALATION_AGE:` (strict greater-than) while the acceptance criteria require escalation for tickets "48 hours or more", i.e., >= 48h, so the boundary condition is excluded.)

> The acceptance criteria require tickets that have existed for 48 hours or more to be escalated. The implementation uses a strict greater-than comparison (`> ESCALATION_AGE`), which skips tickets that are exactly 48 hours old, violating the boundary condition.

**Evidence**

From code:

```
if now - ticket.created_at > ESCALATION_AGE:
```

From ticket:

```
An open ticket that has existed for 48 hours or more is raised by one priority level.
```

From ticket:

```
1. An open ticket that has existed for 48 hours or more is raised by one priority level.
```

### 2. [LOW] Rule: every change in behaviour comes with a test, including the boundary values (for example "exactly 48 hours")

- **Category:** maintainability
- **Location:** `tests/test_service.py (no line given)`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The test suite includes cases for 72h, 1h, urgent, and non‑open tickets but lacks a test for a ticket exactly 48 hours old, as required by the team rule about boundary tests.)

> The new escalation functionality is added, but the test suite does not include a test for the exact 48‑hour boundary, which the team rule requires for any behavioural change.

**Evidence**

From code:

```
def test_an_old_open_ticket_is_escalated_one_level(service):
    ticket = aged(service, 72)
    assert [t.id for t in service.escalate_stale(NOW)] == [ticket.id]
    assert service.get(ticket.id).priority is Priority.HIGH


def test_a_recent_ticket_is_left_alone(service):
    ticket = aged(service, 1)
    assert service.escalate_stale(NOW) == []
    assert service.get(ticket.id).priority is Priority.MEDIUM


def test_urgent_stays_urgent(service):
    ticket = aged(service, 100, Priority.URGENT)
    assert service.escalate_stale(NOW) == []
    assert service.get(ticket.id).priority is Priority.URGENT


def test_tickets_that_are_not_open_are_never_escalated(service):
    ticket = aged(service, 100)
    service.change_status(ticket.id, Status.IN_PROGRESS)
    assert service.escalate_stale(NOW) == []
```

From rules:

```
Every change in behaviour comes with a test, including the boundary values (for example "exactly 48 hours").
```

_1 duplicate finding(s) merged into another finding._

## Dismissed by verification

These candidates were judged unsupported by the verification pass. They are listed so nothing disappears silently; the human reviewer can overrule the verifier.

- **Missing authorization check for ticket priority escalation** (`tickets/service.py:45`, found by security): No requirement or rule in the provided ticket, PR description, or code mandates an authorization check for priority escalation, so the claim cannot be validated.

## Limitations stated by the model

- The repository's authentication and role‑based access control mechanisms are not visible, so the exact impact of the missing check cannot be fully determined.
