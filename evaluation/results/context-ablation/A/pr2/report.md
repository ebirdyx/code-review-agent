# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#2, head `2ad2b01eaa423cc125af1ff5b0df8781230c15a0`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/2)
- **Case:** ebirdyx-ticket-system-demo-pr2-2ad2b01
- **Ticket:** TS-2: Escalate stale tickets
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T01:50:33+00:00
- **Model time:** 14.8 s; tokens: 24198 in / 4957 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 1 finding

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

2 file(s) changed, +53 / -0 lines (1 source, 1 test); file types: .py x2.

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 4.8 s | 5314 / 1543 | 1 candidate finding(s) |
| defects | ok | 3.0 s | 4709 / 847 | 1 candidate finding(s) |
| security | ok | 2.5 s | 4643 / 765 | 1 candidate finding(s) |
| standards | ok | 3.1 s | 4716 / 1293 | 1 candidate finding(s) |
| verify | ok | 2.0 s | 4816 / 509 | 1 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. NOT MET: An open ticket that has existed for 48 hours or more is raised by one priority level.

> The ticket requires escalation for tickets that are 48 hours old or more (>= 48h), but the code only escalates when the age is strictly greater than 48 hours, excluding tickets exactly 48 hours old.

From ticket:

```
An open ticket that has existed for 48 hours or more is raised by one priority level.
```

From code:

```
if now - ticket.created_at > ESCALATION_AGE:
```

Where: `tickets/service.py:50`

### 2. MET: An urgent ticket stays urgent.

> The code only raises the priority when the current priority is not already the highest (URGENT), so urgent tickets remain urgent.

From code:

```
if index < len(PRIORITY_ORDER) - 1:
```

From code:

```
ticket.priority = PRIORITY_ORDER[index + 1]
```

Where: `tickets/service.py:51`

### 3. MET: Tickets that are not open (in progress, resolved, closed) are never escalated.

> The escalation loop iterates only over tickets with status OPEN, so tickets that are not open are never considered for escalation.

From code:

```
for ticket in self.store.list_by_status(Status.OPEN):
```

Where: `tickets/service.py:49`

## Findings

### 1. [MEDIUM] Escalation condition excludes tickets exactly 48 hours old

- **Category:** boundary_condition
- **Location:** `tickets/service.py:50`
- **Location and quotes:** checked against the input
- **Found by:** compliance, defects
- **Verification:** supported (The code uses `if now - ticket.created_at > ESCALATION_AGE:` which excludes tickets exactly 48 hours old, while the acceptance criteria require escalation for tickets 48 hours or more.)

> The code uses a strict greater-than comparison (`> ESCALATION_AGE`) to decide whether a ticket should be escalated. The acceptance criteria require tickets that have existed for 48 hours **or more** to be escalated. Tickets that are exactly 48 hours old will not satisfy the `>` condition, so they will not be escalated, violating the specification. Also reported by compliance as requirement_mismatch: The ticket requires escalation for tickets that are 48 hours old or more (>= 48h), but the code only escalates when the age is strictly greater than 48 hours, excluding tickets exactly 48 hours old.

**Evidence**

From code:

```
if now - ticket.created_at > ESCALATION_AGE:
```

From ticket:

```
An open ticket that has existed for 48 hours or more is raised by one priority level.
```

_2 duplicate finding(s) merged into another finding._

## Dismissed by verification

These candidates were judged unsupported by the verification pass. They are listed so nothing disappears silently; the human reviewer can overrule the verifier.

- **Missing authorization check for ticket escalation** (`tickets/service.py:45`, found by security, standards): No evidence of a required permission check for escalation is present in the ticket, PR description, or code, so the claim of missing authorization cannot be substantiated.
