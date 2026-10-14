# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#1, head `cdc6d0b435f351dcbe672c331bbda655bf4efc7c`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/1)
- **Case:** ebirdyx-ticket-system-demo-pr1-cdc6d0b
- **Ticket:** TS-1: Comments on tickets
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T01:50:11+00:00
- **Model time:** 23.3 s; tokens: 33492 in / 8533 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 2 findings

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

4 file(s) changed, +87 / -2 lines (3 source, 1 test); file types: .py x4.

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 3.0 s | 7167 / 1352 | 0 candidate finding(s) |
| defects | ok | 8.7 s | 6562 / 3102 | 1 candidate finding(s) |
| security | ok | 3.5 s | 6496 / 1080 | 1 candidate finding(s) |
| standards | ok | 4.1 s | 6569 / 1512 | 3 candidate finding(s) |
| verify | ok | 4.7 s | 6698 / 1487 | 2 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: Any user can add a comment to an existing ticket.

> The add_comment method accepts any author string and does not enforce permission checks, allowing any user to add a comment to an existing ticket.

From code:

```
def add_comment(self, ticket_id: int, author: str, body: str) -> Comment:
```

Where: `tickets/service.py:42`

### 2. MET: An empty or whitespace-only comment is rejected.

> The implementation strips whitespace and raises ValueError when the resulting body is empty, rejecting empty or whitespace‑only comments.

From code:

```
if not body:
    raise ValueError("a comment cannot be empty")
```

Where: `tickets/service.py:45`

### 3. MET: A comment is at most 2000 characters.

> MAX_COMMENT is defined as 2000 and the add_comment method raises ValueError when the comment length exceeds this limit, enforcing the maximum length.

From code:

```
if len(body) > MAX_COMMENT:
    raise ValueError(f"a comment is at most {MAX_COMMENT} characters")
```

Where: `tickets/service.py:48`

### 4. MET: A ticket's comments are listed oldest first.

> The comments method returns results from store.list_comments, which queries comments ordered by id (auto‑increment), ensuring oldest‑first ordering.

From code:

```
def comments(self, ticket_id: int) -> list[Comment]:
    """Comments of a ticket, oldest first."""
    self.get(ticket_id)
    return self.store.list_comments(ticket_id)
```

From code:

```
SELECT * FROM comments WHERE ticket_id = ? ORDER BY id
```

Where: `tickets/service.py:52`

## Findings

### 1. [MEDIUM] Missing foreign key enforcement for comments

- **Category:** logic_defect
- **Location:** `tickets/store.py:38`
- **Location and quotes:** checked against the input
- **Found by:** defects
- **Verification:** supported (SQLite connection is created without enabling foreign key constraints, so the foreign key in COMMENTS_SCHEMA is not enforced.)

> The SQLite database is created without enabling foreign key constraints, so inserting a comment with a non‑existent ticket_id will succeed. This can corrupt data integrity because comments may reference tickets that do not exist, even though the service layer checks for ticket existence.

**Evidence**

From code:

```
self._db = sqlite3.connect(path)
self._db.row_factory = sqlite3.Row
self._db.execute(SCHEMA)
self._db.execute(COMMENTS_SCHEMA)
```

From code:

```
"INSERT INTO comments (ticket_id, author, body, created_at) VALUES (?, ?, ?, ?)"
```

### 2. [LOW] Rule: public functions have type hints and a one-line docstring that says what they return or raise

- **Category:** maintainability
- **Location:** `tickets/store.py:88`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (list_comments has a one-line docstring that does not describe its return value, violating the rule requiring such a description.)

> The `list_comments` method's docstring does not specify its return value (a list of Comment objects), which breaches the rule requiring docstrings to state what the function returns.

**Evidence**

From code:

```
"""Comments of a ticket, oldest first."""
```

From rules:

```
Public functions have type hints and a one-line docstring that says what they return or raise.
```

_1 duplicate finding(s) merged into another finding._

## Dismissed by verification

These candidates were judged unsupported by the verification pass. They are listed so nothing disappears silently; the human reviewer can overrule the verifier.

- **Stored XSS risk due to unsanitized comment body** (`tickets/service.py:50`, found by security): The code only stores the comment body; no rendering logic is provided to confirm an XSS risk.
- **Rule: public functions have type hints and a one-line docstring that says what they return or raise** (`tickets/service.py:43`, found by standards): The docstring for add_comment mentions the raised exception, satisfying the rule that a docstring must state what is returned or raised.

## Limitations stated by the model

- The codebase does not include the part that renders comments to users, so the actual XSS impact depends on whether the output is escaped.
