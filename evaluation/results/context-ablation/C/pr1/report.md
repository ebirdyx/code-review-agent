# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#1, head `cdc6d0b435f351dcbe672c331bbda655bf4efc7c`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/1)
- **Case:** ebirdyx-ticket-system-demo-pr1-cdc6d0b
- **Ticket:** TS-1: Comments on tickets
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T01:45:43+00:00
- **Model time:** 17.5 s; tokens: 37238 in / 5323 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 2 findings

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

4 file(s) changed, +87 / -2 lines (3 source, 1 test); file types: .py x4.

## Repository context

Code outside the change that the model was shown, found by matching function names (it can match the wrong function).

- `TicketService.add_comment` (tickets/service.py) is called by 0 other repository function(s) and mentioned in 4 test function(s) (4 added or changed by this change).
- `TicketStore.add_comment` (tickets/store.py) is called by 1 other repository function(s) and mentioned in 4 test function(s) (4 added or changed by this change).
- `TicketStore.list_comments` (tickets/store.py) is called by 1 other repository function(s) and mentioned in no test function.
- `TicketService.comments` (tickets/service.py) is called by 0 other repository function(s) and mentioned in 1 test function(s) (1 added or changed by this change).
- `TicketStore.__init__` (tickets/store.py) is called by 0 other repository function(s) and mentioned in 4 test function(s).
- test of `TicketStore.__init__`: tests/test_service.py:9-11 (`service`)
- class of `TicketService.add_comment`: tickets/service.py:18-19 (`TicketService.__init__`)
- callee of `TicketService.add_comment`: tickets/service.py:30-34 (`TicketService.get`)
- test of `TicketStore.__init__`: tests/test_store.py:9-13 (`test_add_and_get_round_trip`)
- callee of `TicketService.add_comment`: tickets/store.py:54-56 (`TicketStore.get`)
- test of `TicketStore.__init__`: tests/test_store.py:16-22 (`test_list_by_status`)

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 4 | 0 | 0 |  |
| bandit 1.9.4 | ok | 4 | 0 | 0 | 7 warning(s) in test files were ignored (noise in tests) |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 4.5 s | 7976 / 1385 | 0 candidate finding(s) |
| defects | ok | 3.8 s | 7371 / 964 | 0 candidate finding(s) |
| security | ok | 3.5 s | 7305 / 816 | 0 candidate finding(s) |
| standards | ok | 3.8 s | 7378 / 1402 | 3 candidate finding(s) |
| verify | ok | 2.5 s | 7208 / 756 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: Any user can add a comment to an existing ticket.

> The add_comment method accepts any author string and stores the comment without permission checks, allowing any user to add a comment.

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

> The method strips whitespace and raises ValueError when the resulting body is empty, rejecting empty or whitespace‑only comments.

From code:

```
body = body.strip()
if not body:
    raise ValueError("a comment cannot be empty")
```

Where: `tickets/service.py:45`

### 3. MET: A comment is at most 2000 characters.

> MAX_COMMENT is defined as 2000 and the method raises ValueError when the comment length exceeds this limit, enforcing the maximum length.

From code:

```
MAX_COMMENT = 2000
...
if len(body) > MAX_COMMENT:
    raise ValueError(f"a comment is at most {MAX_COMMENT} characters")
```

Where: `tickets/service.py:10`

**Validation problems**

- `quote_not_found`: Quoted code text was not found in the input: "MAX_COMMENT = 2000 ... if len(body) > MAX_COMMENT: raise ValueError(f"a comment is at most {MAX_COMMENT} characters")"

### 4. MET: A ticket's comments are listed oldest first.

> The comments method returns comments ordered by id (ascending) via the store, which yields the oldest comments first.

From code:

```
def comments(self, ticket_id: int) -> list[Comment]:
    """Comments of a ticket, oldest first."""
    self.get(ticket_id)
    return self.store.list_comments(ticket_id)
```

From code:

```
rows = self._db.execute("SELECT * FROM comments WHERE ticket_id = ? ORDER BY id", (ticket_id,)).fetchall()
```

Where: `tickets/service.py:52`

## Findings

### 1. [LOW] Rule: public functions must have docstring stating return or raise

- **Category:** maintainability
- **Location:** `tickets/service.py:43`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The `add_comment` method has a one-line docstring that mentions raised ValueError but does not state the return type, violating the rule that docstrings must say what they return or raise.)

> The public method `add_comment` has a one-line docstring that mentions the raised exception but does not state what the function returns, violating the rule that docstrings must say what they return or raise.

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

### 2. [LOW] Rule: public functions must have docstring stating return or raise

- **Category:** maintainability
- **Location:** `tickets/store.py:87`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The `list_comments` method's docstring describes ordering but does not mention the return value, breaching the rule that public functions' docstrings must state what they return or raise.)

> The public method `list_comments` has a one-line docstring that describes ordering but does not state the return value, violating the rule that docstrings must say what they return or raise.

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

- The review cannot assess risks related to how comment data (author, body) is later rendered or processed outside the provided code, such as potential XSS vulnerabilities.
