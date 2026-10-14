# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#4, head `6d474ad63768ec95c6216d77cee949006b91b220`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/4)
- **Case:** ebirdyx-ticket-system-demo-pr4-6d474ad
- **Ticket:** TS-4: Restrict who can resolve a ticket
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T01:51:07+00:00
- **Model time:** 14.4 s; tokens: 20908 in / 4610 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 3 findings

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

2 file(s) changed, +35 / -0 lines (1 source, 1 test); file types: .py x2.

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 5.3 s | 4653 / 1518 | 2 candidate finding(s) |
| defects | ok | 3.6 s | 4048 / 932 | 2 candidate finding(s) |
| security | ok | 2.0 s | 3982 / 636 | 1 candidate finding(s) |
| standards | ok | 2.3 s | 4055 / 780 | 1 candidate finding(s) |
| verify | ok | 1.9 s | 4170 / 744 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. NOT MET: Only the assignee or an administrator can resolve a ticket.

> The ticket requires that only the assignee or an administrator can resolve a ticket, but the implementation allows the reporter to resolve and never checks the admins set.

From code:

```
def resolve(self, ticket_id: int, actor: str, admins: frozenset[str] = frozenset()) -> Ticket:
```

From code:

```
if actor != ticket.assignee and actor != ticket.reporter:
            raise PermissionError(f"{actor} cannot resolve ticket {ticket_id}")
```

Where: `tickets/service.py:44`

### 2. NOT MET: Anyone else who tries gets a PermissionError and the ticket is unchanged.

> The specification says anyone else should get a PermissionError and the ticket remain unchanged. The code raises PermissionError for non‑assignee/non‑reporter, but it incorrectly permits the reporter, which is not an admin, to resolve the ticket without error.

From code:

```
if actor != ticket.assignee and actor != ticket.reporter:
            raise PermissionError(f"{actor} cannot resolve ticket {ticket_id}")
```

From ticket:

```
2. Anyone else who tries gets a PermissionError and the ticket is unchanged.
```

Where: `tickets/service.py:44`

### 3. MET: Resolving follows the normal workflow (a ticket must be in progress first).

> Resolving a ticket calls the workflow's `transition` function, which enforces the normal status workflow. The test verifies that calling resolve on a ticket that is not IN_PROGRESS raises InvalidTransition, confirming the workflow check.

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

### 1. [HIGH] Insufficient authorization checks in resolve method

- **Category:** security
- **Location:** `tickets/service.py:44`
- **Location and quotes:** checked against the input
- **Found by:** compliance, defects, security
- **Verification:** supported (The resolve method permits the reporter (actor != ticket.assignee and actor != ticket.reporter) and never checks admins, violating the acceptance criteria that only the assignee or an administrator may resolve.)

> The resolve method allows the ticket reporter to resolve the ticket and completely ignores the admins parameter, granting resolution rights to users who should not have them according to the ticket's acceptance criteria, leading to unauthorized ticket resolution. Also reported by compliance, defects as logic_defect: The acceptance criteria require that only the assignee or an administrator can resolve a ticket, but the permission check also permits the ticket reporter to resolve, violating the intended security model. Also reported by compliance as requirement_mismatch: The ticket requires that only the assignee or an administrator can resolve a ticket, but the implementation allows the reporter to resolve a…

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

From code:

```
if actor != ticket.assignee and actor != ticket.reporter:
            raise PermissionError(f"{actor} cannot resolve ticket {ticket_id}")
```

From ticket:

```
2. Anyone else who tries gets a PermissionError and the ticket is unchanged.
```

### 2. [HIGH] Admins parameter is ignored, preventing administrators from resolving tickets

- **Category:** logic_defect
- **Location:** `tickets/service.py:41`
- **Location and quotes:** checked against the input
- **Found by:** defects
- **Verification:** supported (The `admins` parameter is present in the signature but never used in the permission check, so administrators cannot resolve tickets as required.)

> The method signature includes an `admins` parameter intended for administrator checks, but the implementation never uses it, so administrators cannot resolve tickets even when they should be allowed.

**Evidence**

From ticket:

```
1. Only the assignee or an administrator can resolve a ticket.
```

From code:

```
def resolve(self, ticket_id: int, actor: str, admins: frozenset[str] = frozenset()) -> Ticket:
```

From code:

```
if actor != ticket.assignee and actor != ticket.reporter:
```

### 3. [LOW] Rule: public functions must have docstring stating return or raise

- **Category:** maintainability
- **Location:** `tickets/service.py:42`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The public `resolve` function has a docstring that mentions the raised PermissionError but does not state what the function returns, breaching the rule that docstrings must say what they return or raise.)

> The public method `resolve` has a one-line docstring that mentions the raised PermissionError but does not state what the function returns, violating the rule that public functions must have a one-line docstring that says what they return or raise.

**Evidence**

From code:

```
"""Mark a ticket resolved. Raises PermissionError if `actor` is not allowed to."""
```

From rules:

```
Public functions have type hints and a one-line docstring that says what they return or raise.
```

_3 duplicate finding(s) merged into another finding._

## Limitations stated by the model

- The admin set passed to `resolve` is never consulted, so we cannot determine if future code might use it.
- We assume the `transition` function enforces the required workflow, as indicated by the test, but its implementation is not shown.
