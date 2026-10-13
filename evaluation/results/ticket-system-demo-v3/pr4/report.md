# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#4, head `6d474ad63768ec95c6216d77cee949006b91b220`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/4)
- **Case:** ebirdyx-ticket-system-demo-pr4-6d474ad
- **Ticket:** TS-4: Restrict who can resolve a ticket
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v3
- **Date (UTC):** 2026-10-13T23:54:33+00:00
- **Model time:** 11.2 s; tokens: 20567 in / 4790 out
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
| compliance | ok | 3.5 s | 4601 / 1538 | 1 candidate finding(s) |
| defects | ok | 2.8 s | 3996 / 1135 | 2 candidate finding(s) |
| security | ok | 2.2 s | 3930 / 791 | 1 candidate finding(s) |
| standards | ok | 1.9 s | 4003 / 762 | 1 candidate finding(s) |
| verify | ok | 1.5 s | 4037 / 564 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. NOT MET: Only the assignee or an administrator can resolve a ticket.

> The resolve method allows the ticket reporter to resolve a ticket and does not check the admins set, violating the requirement that only the assignee or an administrator may resolve.

From code:

```
if actor != ticket.assignee and actor != ticket.reporter:
```

From ticket:

```
1. Only the assignee or an administrator can resolve a ticket.
```

Where: `tickets/service.py:44`

### 2. MET: Anyone else who tries gets a PermissionError and the ticket is unchanged.

> When an actor who is neither the assignee nor the reporter attempts to resolve, the code raises PermissionError before any state change, and the test confirms the ticket remains IN_PROGRESS.

From code:

```
raise PermissionError(f"{actor} cannot resolve ticket {ticket_id}")
```

From code:

```
with pytest.raises(PermissionError):
    service.resolve(ticket.id, "mallory")
assert service.get(ticket.id).status is Status.IN_PROGRESS
```

Where: `tickets/service.py:45`

### 3. MET: Resolving follows the normal workflow (a ticket must be in progress first).

> The resolve method delegates to the workflow's transition function, which enforces the normal status workflow; the test expects InvalidTransition when resolving a ticket that is not IN_PROGRESS, confirming the behavior.

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

### 1. [HIGH] Authorization check allows reporter to resolve tickets and ignores admin list

- **Category:** security
- **Location:** `tickets/service.py:44`
- **Location and quotes:** checked against the input
- **Found by:** compliance, defects, security
- **Verification:** supported (The resolve method allows the reporter (actor == ticket.reporter) to resolve and never checks the admins set, contradicting the acceptance criteria that only assignee or administrator may resolve.)

> The resolve method permits the ticket reporter to resolve a ticket, which is not intended by the acceptance criteria, and it completely ignores the `admins` parameter, so administrators cannot resolve tickets unless they are also the assignee or reporter, leading to improper authorization enforcement. Also reported by compliance, defects as logic_defect: The `resolve` method checks `if actor != ticket.assignee and actor != ticket.reporter:` which permits the ticket reporter to resolve the ticket and never checks the `admins` set. According to the ticket requirements, only the assignee or an administrator should be allowed to resolve. This logic error can let unauthorized users resolve tickets and prevents administrators from doing so. Also report…

**Evidence**

From code:

```
def resolve(self, ticket_id: int, actor: str, admins: frozenset[str] = frozenset()) -> Ticket:
```

From code:

```
if actor != ticket.assignee and actor != ticket.reporter:
```

From code:

```
raise PermissionError(f"{actor} cannot resolve ticket {ticket_id}")
```

From ticket:

```
1. Only the assignee or an administrator can resolve a ticket.
```

### 2. [LOW] Unused `admins` parameter in resolve method

- **Category:** maintainability
- **Location:** `tickets/service.py:41`
- **Location and quotes:** checked against the input
- **Found by:** defects
- **Verification:** supported (The `admins` parameter is present in the resolve method signature but is never referenced in the function body, making it unused.)

> The `resolve` method signature includes an `admins` frozenset argument that is never referenced inside the function body, making the parameter dead code and potentially confusing future maintainers.

**Evidence**

From code:

```
def resolve(self, ticket_id: int, actor: str, admins: frozenset[str] = frozenset()) -> Ticket:
```

### 3. [LOW] Rule: public functions must have docstring describing return

- **Category:** maintainability
- **Location:** `tickets/service.py:42`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The docstring for resolve mentions the raised PermissionError but does not state what the function returns, violating the team rule that public functions must have a one‑line docstring describing the return or raise.)

> The newly added `resolve` method has a one-line docstring that mentions the raised PermissionError but does not state what the function returns, violating the rule that public functions must have a docstring that says what they return or raise.

**Evidence**

From code:

```
"""Mark a ticket resolved. Raises PermissionError if `actor` is not allowed to."""
```

From rules:

```
Public functions have type hints and a one-line docstring that says what they return or raise.
```

_2 duplicate finding(s) merged into another finding._
