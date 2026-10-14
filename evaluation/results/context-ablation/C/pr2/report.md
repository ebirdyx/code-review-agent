# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#2, head `2ad2b01eaa423cc125af1ff5b0df8781230c15a0`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/2)
- **Case:** ebirdyx-ticket-system-demo-pr2-2ad2b01
- **Ticket:** TS-2: Escalate stale tickets
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T01:46:06+00:00
- **Model time:** 14.9 s; tokens: 26447 in / 5054 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 2 findings

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

2 file(s) changed, +53 / -0 lines (1 source, 1 test); file types: .py x2.

## Repository context

Code outside the change that the model was shown, found by matching function names (it can match the wrong function).

- `TicketService.escalate_stale` (tickets/service.py) is called by 0 other repository function(s) and mentioned in 4 test function(s) (4 added or changed by this change).
- class of `TicketService.escalate_stale`: tickets/service.py:21-22 (`TicketService.__init__`)
- callee of `TicketService.escalate_stale`: tickets/store.py:53-55 (`TicketStore.list_by_status`)
- callee of `TicketService.escalate_stale`: tickets/store.py:46-51 (`TicketStore.save`)

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 2 | 0 | 0 |  |
| bandit 1.9.4 | ok | 2 | 0 | 0 | 12 warning(s) in test files were ignored (noise in tests) |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 4.3 s | 5786 / 1393 | 1 candidate finding(s) |
| defects | ok | 2.8 s | 5181 / 891 | 1 candidate finding(s) |
| security | ok | 2.9 s | 5115 / 745 | 0 candidate finding(s) |
| standards | ok | 3.5 s | 5188 / 1329 | 1 candidate finding(s) |
| verify | ok | 2.0 s | 5177 / 696 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. NOT MET: An open ticket that has existed for 48 hours or more is raised by one priority level.

> The code escalates tickets only when `now - ticket.created_at > ESCALATION_AGE`, which excludes tickets that are exactly 48 hours old. The acceptance criterion requires escalation for tickets that have existed for 48 hours **or more**, i.e., it should use >=.

From code:

```
if now - ticket.created_at > ESCALATION_AGE:
```

From ticket:

```
An open ticket that has existed for 48 hours or more is raised by one priority level.
```

Where: `tickets/service.py:50`

### 2. MET: An urgent ticket stays urgent.

> Urgent tickets have the highest priority in `PRIORITY_ORDER`; the escalation logic only raises priority when the current index is less than the last index, so urgent tickets are left unchanged.

From code:

```
if index < len(PRIORITY_ORDER) - 1:
```

From code:

```
ticket.priority = PRIORITY_ORDER[index + 1]
```

From code:

```
PRIORITY_ORDER = [Priority.LOW, Priority.MEDIUM, Priority.HIGH, Priority.URGENT]
```

From pr_description:

```
Urgent tickets stay urgent
```

From code:

```
assert service.get(ticket.id).priority is Priority.URGENT
```

Where: `tickets/service.py:52`

### 3. MET: Tickets that are not open (in progress, resolved, closed) are never escalated.

> The escalation loop iterates only over tickets with status `Status.OPEN`; tickets in other statuses are never considered for escalation.

From code:

```
for ticket in self.store.list_by_status(Status.OPEN):
```

From code:

```
assert service.escalate_stale(NOW) == []
```

From ticket:

```
Tickets that are not open (in progress, resolved, closed) are never escalated.
```

Where: `tickets/service.py:49`

## Findings

### 1. [MEDIUM] Escalation condition excludes tickets exactly 48 hours old

- **Category:** boundary_condition
- **Location:** `tickets/service.py:50`
- **Location and quotes:** checked against the input
- **Found by:** compliance, defects
- **Verification:** supported (The code uses `if now - ticket.created_at > ESCALATION_AGE:` which excludes tickets exactly 48 hours old, contradicting the acceptance criterion that requires escalation for tickets 48 hours or more.)

> The function uses `if now - ticket.created_at > ESCALATION_AGE:` which only escalates tickets older than 48 hours. The acceptance criteria require tickets that have existed for 48 hours **or more** to be escalated, so tickets exactly 48 hours old are incorrectly left unchanged. Also reported by compliance as requirement_mismatch: The code escalates tickets only when `now - ticket.created_at > ESCALATION_AGE`, which excludes tickets that are exactly 48 hours old. The acceptance criterion requires escalation for tickets that have existed for 48 hours **or more**, i.e., it should use >=.

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
An open ticket that has existed for 48 hours or more is raised by one priority level.
```

### 2. [LOW] Rule: Every change in behaviour comes with a test, including the boundary values

- **Category:** maintainability
- **Location:** `tests/test_service.py (no line given)`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (Team rule 4 requires a test for the exact 48‑hour boundary, but the added tests only cover 72 hours, 1 hour, urgent, and non‑open cases, lacking a test for exactly 48 hours.)

> The new escalation logic depends on a 48‑hour threshold, but the added test suite does not include a test for the exact boundary value (exactly 48 hours). According to team rule 4, such a boundary test is required.

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
4. Every change in behaviour comes with a test, including the boundary values (for example "exactly 48 hours").
```

_1 duplicate finding(s) merged into another finding._

## Limitations stated by the model

- The repository's authentication/authorization model and how TicketService methods are exposed (e.g., via an API) are not provided, so we cannot determine if the new public method `escalate_stale` lacks required permission checks.
