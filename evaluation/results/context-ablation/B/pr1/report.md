# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#1, head `cdc6d0b435f351dcbe672c331bbda655bf4efc7c`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/1)
- **Case:** ebirdyx-ticket-system-demo-pr1-cdc6d0b
- **Ticket:** TS-1: Comments on tickets
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T01:47:55+00:00
- **Model time:** 17.1 s; tokens: 33805 in / 6252 out
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
| compliance | ok | 3.4 s | 7242 / 1167 | 0 candidate finding(s) |
| defects | ok | 4.5 s | 6637 / 1583 | 0 candidate finding(s) |
| security | ok | 4.1 s | 6571 / 1315 | 1 candidate finding(s) |
| standards | ok | 3.7 s | 6644 / 1388 | 2 candidate finding(s) |
| verify | ok | 2.1 s | 6711 / 799 | 1 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: Any user can add a comment to an existing ticket.

> The add_comment method does not enforce any author restrictions, allowing any user to add a comment.

From code:

```
def add_comment(self, ticket_id: int, author: str, body: str) -> Comment:
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

> MAX_COMMENT is defined as 2000 and the method raises ValueError when the comment length exceeds this limit, enforcing the at‑most‑2000‑character rule.

From code:

```
MAX_COMMENT = 2000
...
        if len(body) > MAX_COMMENT:
            raise ValueError(f"a comment is at most {MAX_COMMENT} characters")
```

Where: `tickets/service.py:48`

**Validation problems**

- `quote_not_found`: Quoted code text was not found in the input: "MAX_COMMENT = 2000 ... if len(body) > MAX_COMMENT: raise ValueError(f"a comment is at most {MAX_COMMENT} characters")"

### 4. MET: A ticket's comments are listed oldest first.

> The comments method returns results from store.list_comments, which selects rows ordered by id (auto‑increment), ensuring oldest comments appear first.

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

### 1. [LOW] Rule: public function docstring must describe return or raise

- **Category:** maintainability
- **Location:** `tickets/service.py:53`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The public method `comments` has a one-line docstring that does not describe its return value, violating team rule 3 which requires such a description.)

> The public method `comments` has a docstring that does not state what the function returns or raises, violating the team rule that public functions must have a one-line docstring describing the return value or raised exceptions.

**Evidence**

From code:

```
"""Comments of a ticket, oldest first."""
```

From rules:

```
3. Public functions have type hints and a one-line docstring that says what they return or raise.
```

### 2. [LOW] Rule: public function docstring must describe return or raise

- **Category:** maintainability
- **Location:** `tickets/store.py:87`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The public method `list_comments` has a one-line docstring that does not describe its return value, violating team rule 3 which requires such a description.)

> The public method `list_comments` has a docstring that does not mention what the function returns or raises, violating the team rule requiring such a description.

**Evidence**

From code:

```
"""Comments of a ticket, oldest first."""
```

From rules:

```
3. Public functions have type hints and a one-line docstring that says what they return or raise.
```

## Dismissed by verification

These candidates were judged unsupported by the verification pass. They are listed so nothing disappears silently; the human reviewer can overrule the verifier.

- **Stored XSS risk in comment body** (`tickets/service.py:42`, found by security): The code stores comment bodies unchanged, but no evidence is provided that they are later rendered as HTML, so an XSS risk cannot be confirmed from the given material.

## Limitations stated by the model

- The review cannot confirm how comment bodies are later rendered; the XSS risk is inferred from storage of raw input without sanitization.
