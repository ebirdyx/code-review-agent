# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#2, head `2ad2b01eaa423cc125af1ff5b0df8781230c15a0`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/2)
- **Case:** ebirdyx-ticket-system-demo-pr2-2ad2b01
- **Ticket:** TS-2: Escalate stale tickets
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T01:48:19+00:00
- **Model time:** 17.2 s; tokens: 24736 in / 5998 out
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
| compliance | ok | 5.6 s | 5389 / 2016 | 2 candidate finding(s) |
| defects | ok | 2.3 s | 4784 / 657 | 1 candidate finding(s) |
| security | ok | 3.3 s | 4718 / 1025 | 1 candidate finding(s) |
| standards | ok | 3.6 s | 4791 / 1174 | 1 candidate finding(s) |
| verify | ok | 3.1 s | 5054 / 1126 | 2 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. NOT MET: An open ticket that has existed for 48 hours or more is raised by one priority level.

> The code checks `if now - ticket.created_at > ESCALATION_AGE:` which requires the ticket to be older than 48 hours, excluding tickets that are exactly 48 hours old. The acceptance criterion requires escalation for tickets that have existed for 48 hours **or more**, so tickets exactly 48 hours old would not be escalated, violating the requirement.

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

> Urgent tickets are not escalated because the priority index check prevents moving beyond the highest priority (URGENT). The code leaves urgent tickets unchanged, satisfying the criterion.

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
assert service.get(ticket.id).priority is Priority.URGENT
```

Where: `tickets/service.py:51`

### 3. MET: Tickets that are not open (in progress, resolved, closed) are never escalated.

> The escalation loop iterates only over tickets with status `Status.OPEN`, so tickets that are not open are never considered for escalation, fulfilling the requirement.

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
assert service.escalate_stale(NOW) == []
```

Where: `tickets/service.py:49`

## Findings

### 1. [MEDIUM] Escalation condition excludes tickets exactly 48 hours old

- **Category:** boundary_condition
- **Location:** `tickets/service.py:50`
- **Location and quotes:** checked against the input
- **Found by:** compliance, defects
- **Verification:** supported (The code checks `if now - ticket.created_at > ESCALATION_AGE:` with `ESCALATION_AGE = timedelta(hours=48)`, which excludes tickets that are exactly 48 hours old, contradicting the acceptance criterion that tickets 48 hours or more must be escalated.)

> The acceptance criteria require tickets that have existed for 48 hours or more to be escalated. The code uses a strict greater-than comparison (`> ESCALATION_AGE`), which skips tickets that are exactly 48 hours old, causing them not to be escalated. Also reported by compliance as requirement_mismatch: The code checks `if now - ticket.created_at > ESCALATION_AGE:` which requires the ticket to be older than 48 hours, excluding tickets that are exactly 48 hours old. The acceptance criterion requires escalation for tickets that have existed for 48 hours **or more**, so tickets exactly 48 hours old would not be escalated, violating the requirement.

**Evidence**

From code:

```
if now - ticket.created_at > ESCALATION_AGE:
```

From code:

```
ESCALATION_AGE = timedelta(hours=48)
```

From ticket:

```
1. An open ticket that has existed for 48 hours or more is raised by one priority level.
```

### 2. [LOW] Rule: every change in behaviour comes with a test, including the boundary values

- **Category:** maintainability
- **Location:** `tickets/service.py:45`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The test suite lacks a test for the exact 48‑hour boundary, violating team rule 4 which requires tests for boundary values of new behaviour.)

> The new public method `escalate_stale` introduces behaviour that escalates tickets older than 48 hours, but the test suite does not include a test for the exact 48‑hour boundary, violating the team's rule that every behavioural change must be covered by a test including boundary values.

**Evidence**

From code:

```
def escalate_stale(self, now: datetime | None = None) -> list[Ticket]:
```

From rules:

```
4. Every change in behaviour comes with a test, including the boundary values (for example "exactly 48 hours").
```

_1 duplicate finding(s) merged into another finding._

## Dismissed by verification

These candidates were judged unsupported by the verification pass. They are listed so nothing disappears silently; the human reviewer can overrule the verifier.

- **Missing authorization check in ticket escalation** (`tickets/service.py:45`, found by security): No rule or requirement in the provided ticket, PR description, or team rules mandates an authorization check for `escalate_stale`, so the claim of a missing permission check is not substantiated.
- **Method returns list of changed tickets, which was not specified** (`tickets/service.py:45`, found by compliance): The ticket and PR description do not specify a return value, but returning a list of changed tickets is not prohibited and does not conflict with the stated requirements.
