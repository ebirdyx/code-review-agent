# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#1, head `cdc6d0b435f351dcbe672c331bbda655bf4efc7c`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/1)
- **Case:** ebirdyx-ticket-system-demo-pr1-cdc6d0b
- **Ticket:** TS-1: Comments on tickets
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v3
- **Date (UTC):** 2026-10-13T23:52:27+00:00
- **Model time:** 16.6 s; tokens: 33031 in / 6677 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 3 findings

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
| compliance | ok | 4.2 s | 7103 / 1844 | 0 candidate finding(s) |
| defects | ok | 5.0 s | 6498 / 1720 | 1 candidate finding(s) |
| security | ok | 2.2 s | 6432 / 621 | 0 candidate finding(s) |
| standards | ok | 3.8 s | 6505 / 1596 | 3 candidate finding(s) |
| verify | ok | 2.2 s | 6493 / 896 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: Any user can add a comment to an existing ticket.

> The add_comment method accepts any author string and does not enforce permission checks, allowing any user to add a comment to an existing ticket.

From code:

```
def add_comment(self, ticket_id: int, author: str, body: str) -> Comment:
    """Add a comment to an existing ticket. Raises ValueError if it is empty or longer than MAX_COMMENT."""
    self.get(ticket_id)  # raises TicketNotFound
    body = body.strip()
    if not body:
        raise ValueError("a comment cannot be empty")
    if len(body) > MAX_COMMENT:
        raise ValueError(f"a comment is at most {MAX_COMMENT} characters")
    return self.store.add_comment(Comment(id=0, ticket_id=ticket_id, author=author, body=body))
```

Where: `tickets/service.py:42`

### 2. MET: An empty or whitespace-only comment is rejected.

> add_comment strips whitespace and raises ValueError when the resulting body is empty, rejecting empty or whitespace‑only comments.

From code:

```
body = body.strip()
if not body:
    raise ValueError("a comment cannot be empty")
```

Where: `tickets/service.py:45`

### 3. MET: A comment is at most 2000 characters.

> MAX_COMMENT is defined as 2000 and add_comment raises a ValueError if the comment length exceeds this limit, enforcing the "at most 2000 characters" rule.

From code:

```
MAX_COMMENT = 2000
```

From code:

```
if len(body) > MAX_COMMENT:
    raise ValueError(f"a comment is at most {MAX_COMMENT} characters")
```

Where: `tickets/service.py:10`

### 4. MET: A ticket's comments are listed oldest first.

> list_comments queries the comments table ordered by id, which reflects insertion order, and the test asserts that comments are returned oldest first.

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

### 1. [MEDIUM] add_comment does not verify ticket existence

- **Category:** error_handling
- **Location:** `tickets/store.py:76`
- **Location and quotes:** checked against the input
- **Found by:** defects
- **Verification:** supported (The add_comment method in tickets/store.py inserts a comment without checking ticket existence, as shown by the code snippet lacking any verification.)

> The store's add_comment method inserts a comment row without checking that the referenced ticket_id exists. If called directly (bypassing TicketService), it can create orphan comments, violating data integrity.

**Evidence**

From code:

```
def add_comment(self, comment: Comment) -> Comment:
        """Insert a comment and return it with its new id."""
        cursor = self._db.execute(
            "INSERT INTO comments (ticket_id, author, body, created_at) VALUES (?, ?, ?, ?)",
            (comment.ticket_id, comment.author, comment.body, comment.created_at.isoformat()),
        )
```

### 2. [LOW] Rule: Public functions have type hints and a one-line docstring that says what they return or raise

- **Category:** maintainability
- **Location:** `tickets/service.py:43`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The add_comment method in tickets/service.py has a type hint but its docstring only mentions the raised exception and does not state the return value, violating the team rule.)

> The public method `add_comment` has a type hint but its one-line docstring mentions only the raised exception and does not state what the function returns, violating the rule that docstrings must say what they return or raise.

**Evidence**

From code:

```
"""Add a comment to an existing ticket. Raises ValueError if it is empty or longer than MAX_COMMENT."""
```

From rules:

```
Public functions have type hints and a one-line docstring that says what they return or raise.
```

From code:

```
"""Comments of a ticket, oldest first."""
```

### 3. [LOW] Rule: Public functions have type hints and a one-line docstring that says what they return or raise

- **Category:** maintainability
- **Location:** `tickets/store.py:87`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The list_comments method in tickets/store.py has a type hint but its docstring does not specify what it returns, violating the team rule.)

> The public method `list_comments` has a type hint but its docstring does not specify the return value, violating the rule that docstrings must indicate what they return or raise.

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

## Limitations stated by the model

- The review cannot determine if comment bodies are later rendered in a web context without proper escaping, which could lead to XSS vulnerabilities.
