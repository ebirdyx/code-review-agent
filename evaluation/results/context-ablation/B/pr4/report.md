# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#4, head `6d474ad63768ec95c6216d77cee949006b91b220`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/4)
- **Case:** ebirdyx-ticket-system-demo-pr4-6d474ad
- **Ticket:** TS-4: Restrict who can resolve a ticket
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T01:49:04+00:00
- **Model time:** 14.4 s; tokens: 21168 in / 5100 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 1 finding

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
| compliance | ok | 5.0 s | 4740 / 1921 | 1 candidate finding(s) |
| defects | ok | 2.8 s | 4135 / 992 | 2 candidate finding(s) |
| security | ok | 2.6 s | 4069 / 725 | 1 candidate finding(s) |
| standards | ok | 2.4 s | 4142 / 711 | 1 candidate finding(s) |
| verify | ok | 2.3 s | 4082 / 751 | 1 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. NOT MET: Only the assignee or an administrator can resolve a ticket.

> The code permits the reporter to resolve tickets and does not check administrators, violating the requirement that only the assignee or an administrator may resolve a ticket.

From ticket:

```
1. Only the assignee or an administrator can resolve a ticket.
```

From code:

```
if actor != ticket.assignee and actor != ticket.reporter:
```

Where: `tickets/service.py:44`

### 2. MET: Anyone else who tries gets a PermissionError and the ticket is unchanged.

> The resolve method raises PermissionError for any actor who is neither the assignee nor the reporter, and the ticket status remains unchanged as verified by the test.

From ticket:

```
2. Anyone else who tries gets a PermissionError and the ticket is unchanged.
```

From code:

```
if actor != ticket.assignee and actor != ticket.reporter:
            raise PermissionError(f"{actor} cannot resolve ticket {ticket_id}")
```

Where: `tickets/service.py:44`

### 3. MET: Resolving follows the normal workflow (a ticket must be in progress first).

> Resolving a ticket invokes the workflow transition, which raises InvalidTransition if the ticket is not in progress, as demonstrated by the test expecting InvalidTransition when resolve is called before the ticket is IN_PROGRESS.

From ticket:

```
3. Resolving follows the normal workflow (a ticket must be in progress first).
```

From code:

```
transition(ticket, Status.RESOLVED)
```

From pr_description:

```
Resolving follows the normal workflow.
```

From code:

```
with pytest.raises(InvalidTransition):
        service.resolve(ticket.id, "bob")
```

Where: `tests/test_service.py:74`

## Findings

### 1. [HIGH] Insufficient permission check in resolve method

- **Category:** security
- **Location:** `tickets/service.py:44`
- **Location and quotes:** checked against the input
- **Found by:** compliance, defects, security
- **Verification:** supported (The resolve method allows the reporter (actor == ticket.reporter) and never checks the admins set, contradicting the ticket requirement that only the assignee or an administrator may resolve.)

> The `resolve` method permits the ticket reporter to resolve a ticket and completely ignores the `admins` parameter, allowing users who should not have permission (reporters) to resolve tickets and preventing administrators from doing so, violating the intended access control. Also reported by compliance, defects as requirement_mismatch: The code permits the reporter to resolve tickets and does not check administrators, violating the requirement that only the assignee or an administrator may resolve a ticket.

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

From code:

```
if actor != ticket.assignee and actor != ticket.reporter:
```

From ticket:

```
Only the assignee or an administrator can resolve a ticket.
```

From code:

```
def resolve(self, ticket_id: int, actor: str, admins: frozenset[str] = frozenset()) -> Ticket:
```

_3 duplicate finding(s) merged into another finding._

## Dismissed by verification

These candidates were judged unsupported by the verification pass. They are listed so nothing disappears silently; the human reviewer can overrule the verifier.

- **Rule: Public functions have type hints and a one-line docstring that says what they return or raise** (`tickets/service.py:42`, found by standards): The rule requires the docstring to state what the function returns or raises; the docstring already mentions the raised PermissionError, satisfying the "or raise" condition, so the claim of violation is not supported.
