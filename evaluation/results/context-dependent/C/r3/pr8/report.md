# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#8, head `86b5142f50496cc8cca3af7db2ba917962ad6338`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/8)
- **Case:** ebirdyx-ticket-system-demo-pr8-86b5142
- **Ticket:** TS-8: Workflow transitions must not modify their input
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T04:58:13+00:00
- **Model time:** 10.3 s; tokens: 18820 in / 3304 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 1 finding

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

2 file(s) changed, +8 / -5 lines (1 source, 1 test); file types: .py x2.

## Repository context

Code outside the change that the model was shown, found by matching function names (it can match the wrong function).

- `transition` (tickets/workflow.py) is called by 1 other repository function(s) and mentioned in 3 test function(s) (1 added or changed by this change).
- caller of `transition`: tickets/service.py:41-45 (`TicketService.change_status`)
- test of `transition`: tests/test_workflow.py:19-22 (`test_closed_is_final`)
- test of `transition`: tests/test_workflow.py:25-27 (`test_open_cannot_jump_to_resolved`)

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 2 | 0 | 0 |  |
| bandit 1.9.4 | ok | 2 | 0 | 0 | 2 warning(s) in test files were ignored (noise in tests) |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 3.5 s | 4314 / 1090 | 0 candidate finding(s) |
| defects | ok | 1.9 s | 3709 / 583 | 1 candidate finding(s) |
| security | ok | 2.1 s | 3643 / 601 | 0 candidate finding(s) |
| standards | ok | 1.9 s | 3716 / 538 | 0 candidate finding(s) |
| verify | ok | 1.5 s | 3438 / 492 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: transition returns a new ticket with the new status.

> The `transition` function now returns a new Ticket instance with the new status.

From code:

```
def transition(ticket: Ticket, new_status: Status) -> Ticket:
```

From code:

```
return replace(ticket, status=new_status)
```

From code:

```
moved = transition(t, end)
```

From code:

```
assert moved.status is end
```

Where: `tickets/workflow.py:25`

### 2. MET: The ticket passed to transition is not modified.

> The original ticket object is left unchanged; a copy is returned instead.

From code:

```
return replace(ticket, status=new_status)
```

From code:

```
assert t.status is start  # the argument is left alone
```

Where: `tests/test_workflow.py:16`

### 3. MET: A change that the workflow does not allow still raises InvalidTransition.

> When a disallowed status transition is attempted, `InvalidTransition` is raised.

From code:

```
if new_status not in ALLOWED[ticket.status]:
```

From code:

```
raise InvalidTransition(f"cannot go from {ticket.status.value} to {new_status.value}")
```

From code:

```
with pytest.raises(InvalidTransition):
```

Where: `tickets/workflow.py:24`

## Findings

### 1. [HIGH] Service does not use the new Ticket returned by transition

- **Category:** logic_defect
- **Location:** `tickets/service.py:43`
- **Location and quotes:** checked against the input
- **Found by:** defects
- **Verification:** supported (The `change_status` method in tickets/service.py calls `transition(ticket, new_status)` without assigning its returned Ticket, then saves and returns the original ticket, so the status change is not persisted.)

> After the workflow change, `transition` returns a new Ticket instead of mutating the original. The `change_status` method in `tickets/service.py` still calls `transition(ticket, new_status)` without capturing the returned Ticket, then saves and returns the original unmodified ticket. This results in the status not being updated in persisted data, breaking the intended behavior.

**Evidence**

From code:

```
    def change_status(self, ticket_id: int, new_status: Status) -> Ticket:
        ticket = self.get(ticket_id)
        transition(ticket, new_status)
        self.store.save(ticket)
        return ticket
```

## Limitations stated by the model

- The definition of the Ticket dataclass (including its fields and any sensitive data it may contain) is not provided, so we cannot assess whether returning a shallow copy via dataclasses.replace could expose or leak sensitive information.
