# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#4, head `6d474ad63768ec95c6216d77cee949006b91b220`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/4)
- **Case:** ebirdyx-ticket-system-demo-pr4-6d474ad
- **Ticket:** TS-4: Restrict who can resolve a ticket
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v2
- **Date (UTC):** 2026-10-13T23:02:22+00:00
- **Model time:** 21.0 s; tokens: 20290 in / 4984 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 3 findings

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

2 file(s) changed, +35 / -0 lines (1 source, 1 test); file types: .py x2.

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 2 | 0 | 0 |  |
| bandit 1.9.4 | ok | 2 | 0 | 0 | 7 warning(s) in test files were ignored (noise in tests) |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 6.1 s | 4444 / 1475 | 1 candidate finding(s) |
| defects | ok | 3.0 s | 3996 / 593 | 1 candidate finding(s) |
| security | ok | 4.1 s | 3930 / 840 | 1 candidate finding(s) |
| standards | ok | 3.0 s | 3868 / 843 | 1 candidate finding(s) |
| verify | ok | 5.4 s | 4052 / 1233 | 1 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. NOT MET: Only the assignee or an administrator can resolve a ticket.

> The resolve method allows the reporter to resolve a ticket and does not check the admins set, violating the requirement that only the assignee or an administrator may resolve.

From code:

```
def resolve(self, ticket_id: int, actor: str, admins: frozenset[str] = frozenset()) -> Ticket:
    """Mark a ticket resolved. Raises PermissionError if `actor` is not allowed to."""
    ticket = self.get(ticket_id)
    if actor != ticket.assignee and actor != ticket.reporter:
        raise PermissionError(f"{actor} cannot resolve ticket {ticket_id}")
```

Where: `tickets/service.py:41`

### 2. MET: Anyone else who tries gets a PermissionError and the ticket is unchanged.

> When an actor other than the assignee (or reporter) attempts to resolve, the code raises PermissionError before any state change, and the ticket remains unchanged.

From code:

```
if actor != ticket.assignee and actor != ticket.reporter:
    raise PermissionError(f"{actor} cannot resolve ticket {ticket_id}")
```

From code:

```
with pytest.raises(PermissionError):
    service.resolve(ticket.id, "mallory")
assert service.get(ticket.id).status is Status.IN_PROGRESS
```

Where: `tickets/service.py:44`

### 3. MET: Resolving follows the normal workflow (a ticket must be in progress first).

> The resolve method delegates to the workflow's transition function, which enforces that a ticket must be IN_PROGRESS before it can be resolved; the test expects InvalidTransition when this precondition is not met.

From code:

```
transition(ticket, Status.RESOLVED)
```

From code:

```
with pytest.raises(InvalidTransition):
    service.resolve(ticket.id, "bob")
```

Where: `tickets/service.py:46`

## Findings

### 1. [HIGH] Criterion 1 not met: Only the assignee or an administrator can resolve a ticket.

- **Category:** requirement_mismatch
- **Location:** `tickets/service.py:41`
- **Location and quotes:** checked against the input
- **Found by:** compliance
- **Verification:** supported (The resolve method checks `actor != ticket.assignee and actor != ticket.reporter`, allowing the reporter and never checking the admins set, contrary to the requirement that only assignee or admin may resolve.)

> The resolve method allows the reporter to resolve a ticket and does not check the admins set, violating the requirement that only the assignee or an administrator may resolve.

**Evidence**

From code:

```
def resolve(self, ticket_id: int, actor: str, admins: frozenset[str] = frozenset()) -> Ticket:
    """Mark a ticket resolved. Raises PermissionError if `actor` is not allowed to."""
    ticket = self.get(ticket_id)
    if actor != ticket.assignee and actor != ticket.reporter:
        raise PermissionError(f"{actor} cannot resolve ticket {ticket_id}")
```

### 2. [HIGH] Reporter allowed to resolve tickets

- **Category:** logic_defect
- **Location:** `tickets/service.py:44`
- **Location and quotes:** checked against the input
- **Found by:** defects
- **Verification:** supported (The code permits `actor == ticket.reporter` to resolve, which violates the acceptance criterion that only the assignee or an administrator may resolve.)

> The resolve method permits the ticket reporter to resolve a ticket (actor == ticket.reporter) which violates the acceptance criteria that only the assignee or an administrator may resolve a ticket. This can let unauthorized users close tickets.

**Evidence**

From ticket:

```
1. Only the assignee or an administrator can resolve a ticket.
```

From code:

```
if actor != ticket.assignee and actor != ticket.reporter:
```

### 3. [MEDIUM] Reporter allowed to resolve tickets, bypassing intended permission model

- **Category:** security
- **Location:** `tickets/service.py:44`
- **Location and quotes:** checked against the input
- **Found by:** security
- **Verification:** supported (The implementation authorizes the reporter (and ignores the admins parameter), creating an unauthorized resolution path against the specified criteria.)

> The resolve method authorizes a user if they are the ticket's assignee OR the reporter, but the ticket's acceptance criteria require only the assignee or an administrator to resolve; this permits reporters to resolve tickets they should not be able to, creating an unauthorized action.

**Evidence**

From code:

```
def resolve(self, ticket_id: int, actor: str, admins: frozenset[str] = frozenset()) -> Ticket:
```

From code:

```
if actor != ticket.assignee and actor != ticket.reporter:
    raise PermissionError(f"{actor} cannot resolve ticket {ticket_id}")
```

From ticket:

```
1. Only the assignee or an administrator can resolve a ticket.
```

## Dismissed by verification

These candidates were judged unsupported by the verification pass. They are listed so nothing disappears silently; the human reviewer can overrule the verifier.

- **Rule: public functions docstring must describe return** (`tickets/service.py:42`, found by standards): Assessing rule compliance is outside the verifier's scope; only the team-rules specialist should report such violations.
