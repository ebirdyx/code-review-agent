# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#8, head `86b5142f50496cc8cca3af7db2ba917962ad6338`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/8)
- **Case:** ebirdyx-ticket-system-demo-pr8-86b5142
- **Ticket:** TS-8: Workflow transitions must not modify their input
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T04:56:58+00:00
- **Model time:** 11.1 s; tokens: 17159 in / 3098 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 1 finding

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

2 file(s) changed, +8 / -5 lines (1 source, 1 test); file types: .py x2.

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 2 | 0 | 0 |  |
| bandit 1.9.4 | ok | 2 | 0 | 0 | 2 warning(s) in test files were ignored (noise in tests) |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 3.4 s | 3997 / 999 | 0 candidate finding(s) |
| defects | ok | 2.9 s | 3392 / 680 | 1 candidate finding(s) |
| security | ok | 1.5 s | 3326 / 295 | 0 candidate finding(s) |
| standards | ok | 2.0 s | 3399 / 554 | 0 candidate finding(s) |
| verify | ok | 1.9 s | 3045 / 570 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: transition returns a new ticket with the new status.

> The `transition` function returns a new Ticket instance with the new status using `replace`.

From code:

```
return replace(ticket, status=new_status)
```

Where: `tickets/workflow.py:25`

### 2. MET: The ticket passed to transition is not modified.

> The original ticket object is not modified; the test asserts the original status remains unchanged.

From code:

```
assert t.status is start  # the argument is left alone
```

Where: `tests/test_workflow.py:16`

### 3. MET: A change that the workflow does not allow still raises InvalidTransition.

> When a transition is not allowed, the function raises `InvalidTransition`.

From code:

```
raise InvalidTransition(f"cannot go from {ticket.status.value} to {new_status.value}")
```

Where: `tickets/workflow.py:24`

## Findings

### 1. [MEDIUM] KeyError when ticket status not present in ALLOWED

- **Category:** error_handling
- **Location:** `tickets/workflow.py:23`
- **Location and quotes:** checked against the input
- **Found by:** defects
- **Verification:** supported (The function indexes ALLOWED with ticket.status without checking for key existence, so a Ticket whose status is not a key in ALLOWED would raise a KeyError instead of InvalidTransition.)

> The function accesses ALLOWED[ticket.status] without checking that ticket.status exists as a key. If a Ticket has a status not defined in the ALLOWED mapping (e.g., a new enum value added later), a KeyError will be raised instead of the intended InvalidTransition, breaking error handling expectations.

**Evidence**

From code:

```
if new_status not in ALLOWED[ticket.status]:
```

## Limitations stated by the model

- Ticket model definition is not provided, so potential issues with shallow copying of mutable fields via dataclasses.replace cannot be fully assessed.
- The definition of the Ticket dataclass is not provided, so we cannot assess whether copying it with dataclasses.replace could unintentionally expose or mishandle sensitive fields.
