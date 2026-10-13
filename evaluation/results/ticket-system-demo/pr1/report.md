# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#1, head `cdc6d0b435f351dcbe672c331bbda655bf4efc7c`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/1)
- **Case:** ebirdyx-ticket-system-demo-pr1-cdc6d0b
- **Ticket:** TS-1: Comments on tickets
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v2
- **Date (UTC):** 2026-10-13T23:05:13+00:00
- **Model time:** 23.5 s; tokens: 32563 in / 6556 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 2 findings

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

4 file(s) changed, +87 / -2 lines (3 source, 1 test); file types: .py x4.

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 4 | 0 | 0 |  |
| bandit 1.9.4 | ok | 4 | 0 | 0 | 7 warning(s) in test files were ignored (noise in tests) |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 6.0 s | 6946 / 1984 | 0 candidate finding(s) |
| defects | ok | 7.0 s | 6498 / 1704 | 1 candidate finding(s) |
| security | ok | 3.4 s | 6432 / 629 | 0 candidate finding(s) |
| standards | ok | 3.3 s | 6370 / 931 | 2 candidate finding(s) |
| verify | ok | 4.6 s | 6317 / 1308 | 1 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: Any user can add a comment to an existing ticket.

> The add_comment method accepts any author string without permission checks, allowing any user to add a comment to an existing ticket.

From code:

```
def add_comment(self, ticket_id: int, author: str, body: str) -> Comment:
```

From code:

```
service.add_comment(ticket.id, "bob", "first")
service.add_comment(ticket.id, "carol", "second")
```

Where: `tickets/service.py:42`

### 2. MET: An empty or whitespace-only comment is rejected.

> Empty or whitespace‑only comments are stripped and cause a ValueError, rejecting such inputs.

From code:

```
body = body.strip()
if not body:
    raise ValueError("a comment cannot be empty")
```

From code:

```
with pytest.raises(ValueError, match="cannot be empty"):
    service.add_comment(ticket.id, "bob", body)
```

Where: `tickets/service.py:45`

### 3. MET: A comment is at most 2000 characters.

> MAX_COMMENT is defined as 2000 and the add_comment method raises a ValueError when a comment exceeds this length, enforcing the at‑most‑2000‑character rule.

From code:

```
MAX_COMMENT = 2000
```

From code:

```
if len(body) > MAX_COMMENT:
    raise ValueError(f"a comment is at most {MAX_COMMENT} characters")
```

From code:

```
assert service.add_comment(ticket.id, "bob", "x" * MAX_COMMENT)
with pytest.raises(ValueError, match="at most"):
    service.add_comment(ticket.id, "bob", "x" * (MAX_COMMENT + 1))
```

Where: `tickets/service.py:10`

### 4. MET: A ticket's comments are listed oldest first.

> The comments method returns comments ordered by id via a SQL query with ORDER BY id, which yields the oldest comments first.

From code:

```
rows = self._db.execute("SELECT * FROM comments WHERE ticket_id = ? ORDER BY id", (ticket_id,)).fetchall()
```

From code:

```
assert [c.body for c in service.comments(ticket.id)] == ["first", "second"]
```

Where: `tickets/store.py:88`

## Findings

### 1. [LOW] Rule: Public functions must have a docstring that says what they return or raise

- **Category:** maintainability
- **Location:** `tickets/service.py:53`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The public method `comments` has a one-line docstring "Comments of a ticket, oldest first." which does not explicitly state what the function returns, matching the claim of a missing return description.)

> The public method `comments` has a one-line docstring that does not describe its return value, violating the rule that docstrings must state what the function returns or raises.

**Evidence**

From code:

```
"""Comments of a ticket, oldest first."""
```

From rules:

```
Public functions have type hints and a one-line docstring that says what they return or raise.
```

### 2. [LOW] Rule: Public functions must have a docstring that says what they return or raise

- **Category:** maintainability
- **Location:** `tickets/store.py:88`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The public method `list_comments` also uses the docstring "Comments of a ticket, oldest first." without explicitly describing its return value, confirming the claim.)

> The public method `list_comments` has a one-line docstring that does not describe its return value, violating the rule that docstrings must state what the function returns or raises.

**Evidence**

From code:

```
"""Comments of a ticket, oldest first."""
```

From rules:

```
Public functions have type hints and a one-line docstring that says what they return or raise.
```

## Dismissed by verification

These candidates were judged unsupported by the verification pass. They are listed so nothing disappears silently; the human reviewer can overrule the verifier.

- **Incorrect indentation of COMMENTS_SCHEMA execution** (`tickets/store.py:40`, found by defects): The COMMENTS_SCHEMA execution line is correctly indented within the __init__ method, matching surrounding statements, so no indentation error exists.

## Limitations stated by the model

- The review only covers the provided backend code; potential security issues such as XSS depend on how comment bodies and authors are rendered in the UI, which is not visible here.
