# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#4, head `6d474ad63768ec95c6216d77cee949006b91b220`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/4)
- **Case:** ebirdyx-ticket-system-demo-pr4-6d474ad
- **Ticket:** TS-4: Restrict who can resolve a ticket
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T01:46:47+00:00
- **Model time:** 13.4 s; tokens: 23262 in / 4528 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 1 finding

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

2 file(s) changed, +35 / -0 lines (1 source, 1 test); file types: .py x2.

## Repository context

Code outside the change that the model was shown, found by matching function names (it can match the wrong function).

- `TicketService.resolve` (tickets/service.py) is called by 0 other repository function(s) and mentioned in 3 test function(s) (3 added or changed by this change).
- class of `TicketService.resolve`: tickets/service.py:17-18 (`TicketService.__init__`)
- callee of `TicketService.resolve`: tickets/service.py:29-33 (`TicketService.get`)
- callee of `TicketService.resolve`: tickets/store.py:42-44 (`TicketStore.get`)
- callee of `TicketService.resolve`: tickets/store.py:46-51 (`TicketStore.save`)

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 2 | 0 | 0 |  |
| bandit 1.9.4 | ok | 2 | 0 | 0 | 7 warning(s) in test files were ignored (noise in tests) |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 4.3 s | 5170 / 1444 | 2 candidate finding(s) |
| defects | ok | 2.4 s | 4565 / 643 | 1 candidate finding(s) |
| security | ok | 2.8 s | 4499 / 760 | 1 candidate finding(s) |
| standards | ok | 3.1 s | 4572 / 1186 | 0 candidate finding(s) |
| verify | ok | 1.5 s | 4456 / 495 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. NOT MET: Only the assignee or an administrator can resolve a ticket.

> The ticket requires that only the assignee or an administrator can resolve a ticket, but the implementation also allows the reporter to resolve and never checks the provided admin set.

From code:

```
if actor != ticket.assignee and actor != ticket.reporter:
```

From ticket:

```
1. Only the assignee or an administrator can resolve a ticket.
```

Where: `tickets/service.py:44`

### 2. NOT MET: Anyone else who tries gets a PermissionError and the ticket is unchanged.

> Anyone else (including the reporter) should receive a PermissionError and leave the ticket unchanged, but the code treats the reporter as allowed, so a reporter does not get the required PermissionError.

From code:

```
if actor != ticket.assignee and actor != ticket.reporter:
```

From ticket:

```
2. Anyone else who tries gets a PermissionError and the ticket is unchanged.
```

Where: `tickets/service.py:44`

### 3. MET: Resolving follows the normal workflow (a ticket must be in progress first).

> Resolving uses the workflow `transition` function, which enforces the normal status progression (a ticket must be IN_PROGRESS before it can be RESOLVED). The test suite verifies that calling resolve on a ticket not in progress raises InvalidTransition.

From code:

```
transition(ticket, Status.RESOLVED)
```

From code:

```
with pytest.raises(InvalidTransition):
        service.resolve(ticket.id, "bob")
```

## Findings

### 1. [HIGH] Insufficient authorization check in resolve() allows reporter to resolve tickets

- **Category:** security
- **Location:** `tickets/service.py:44`
- **Location and quotes:** checked against the input
- **Found by:** compliance, defects, security
- **Verification:** supported (The resolve method permits the reporter (actor == ticket.reporter) to resolve a ticket and never checks the admins set, violating the acceptance criteria that only the assignee or an administrator may resolve a ticket.)

> The resolve method permits the ticket reporter to resolve a ticket, contrary to the acceptance criteria that only the assignee or an administrator may resolve, potentially allowing unauthorized users to close tickets. Also reported by compliance, defects as logic_defect: The resolve method allows the ticket reporter to resolve the ticket and does not consider administrators, contrary to the acceptance criteria which require only the assignee or an administrator to be able to resolve. This can let unauthorized users close tickets. Also reported by compliance as requirement_mismatch: The ticket requires that only the assignee or an administrator can resolve a ticke…

**Evidence**

From code:

```
if actor != ticket.assignee and actor != ticket.reporter:
            raise PermissionError(f"{actor} cannot resolve ticket {ticket_id}")
```

From ticket:

```
1. Only the assignee or an administrator can resolve a ticket.
```

From ticket:

```
Only the assignee or an administrator can resolve a ticket.
```

From code:

```
if actor != ticket.assignee and actor != ticket.reporter:
```

From ticket:

```
2. Anyone else who tries gets a PermissionError and the ticket is unchanged.
```

_3 duplicate finding(s) merged into another finding._
