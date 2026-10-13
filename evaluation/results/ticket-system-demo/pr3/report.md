# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#3, head `60559c2aa26af2ffe8c6ccc9751feffc69e96237`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/3)
- **Case:** ebirdyx-ticket-system-demo-pr3-60559c2
- **Ticket:** TS-3: Search tickets by assignee
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v2
- **Date (UTC):** 2026-10-13T23:06:11+00:00
- **Model time:** 20.5 s; tokens: 23246 in / 5372 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 4 findings

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

3 file(s) changed, +23 / -0 lines (2 source, 1 test); file types: .py x3.

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 3 | 0 | 0 |  |
| bandit 1.9.4 | ok | 3 | 1 | 1 | 7 warning(s) in test files were ignored (noise in tests) |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 4.4 s | 5064 / 1184 | 0 candidate finding(s) |
| defects | ok | 4.3 s | 4616 / 911 | 1 candidate finding(s) |
| security | ok | 2.3 s | 4550 / 496 | 1 candidate finding(s) |
| standards | ok | 4.2 s | 4488 / 1266 | 2 candidate finding(s) |
| verify | ok | 6.0 s | 4528 / 1515 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: Tickets can be found by the name of their assignee.

> The service provides a `find_by_assignee` method that delegates to the store's `search_assignee`, returning tickets assigned to the given name.

From code:

```
def find_by_assignee(self, name: str) -> list[Ticket]:
    """Tickets assigned to `name` (case does not matter); empty if nobody matches."""
    return self.store.search_assignee(name.strip())
```

From code:

```
def search_assignee(self, name: str) -> list[Ticket]:
    query = f"SELECT * FROM tickets WHERE LOWER(assignee) = '{name.lower()}' ORDER BY id"
    rows = self._db.execute(query).fetchall()
    return [_from_row(r) for r in rows]
```

Where: `tickets/service.py:41`

### 2. MET: The match ignores upper and lower case.

> The SQL query uses `LOWER(assignee) = '{name.lower()}'`, ensuring the match ignores case.

From code:

```
query = f"SELECT * FROM tickets WHERE LOWER(assignee) = '{name.lower()}' ORDER BY id"
```

Where: `tickets/store.py:65`

### 3. MET: When nobody matches, the result is an empty list.

> When no ticket matches the assignee name, the query returns no rows and the method returns an empty list; a test asserts this behavior.

From code:

```
assert service.find_by_assignee("nobody") == []
```

Where: `tests/test_service.py:61`

## Findings

### 1. [HIGH] bandit B608: Possible SQL injection vector through string-based query construction.

- **Category:** security
- **Location:** `tickets/store.py:65`
- **Location and quotes:** checked against the input
- **Found by:** bandit, security
- **Backed by:** a static-analysis tool (a deterministic check, not put to the verifier's vote)

> Possible SQL injection vector through string-based query construction. (reported by the static-analysis tool bandit, rule B608; a deterministic check, not a model's opinion).

**Evidence**

From code:

```
query = f"SELECT * FROM tickets WHERE LOWER(assignee) = '{name.lower()}' ORDER BY id"
```

From code:

```
def find_by_assignee(self, name: str) -> list[Ticket]:
        """Tickets assigned to `name` (case does not matter); empty if nobody matches."""
        return self.store.search_assignee(name.strip())
```

### 2. [MEDIUM] SQL query built with f-string allows injection or syntax errors on special characters

- **Category:** boundary_condition
- **Location:** `tickets/store.py:65`
- **Location and quotes:** checked against the input
- **Found by:** defects
- **Verification:** supported (The `search_assignee` method builds the SQL query with an f‑string that directly interpolates the user‑provided name, which can lead to injection or syntax errors on special characters.)

> The `search_assignee` method constructs the SQL statement using an f-string that directly interpolates the user‑provided `name` after calling `lower()`. If the name contains characters such as a single quote, the resulting query becomes syntactically invalid or could be exploited for SQL injection, causing the function to fail or return incorrect results. Proper parameter binding should be used to handle all input safely.

**Evidence**

From code:

```
query = f"SELECT * FROM tickets WHERE LOWER(assignee) = '{name.lower()}' ORDER BY id"
```

From code:

```
rows = self._db.execute(query).fetchall()
```

### 3. [LOW] Rule: All SQL uses bound parameters (`?`). Never build SQL with f-strings, `%` or `+`.

- **Category:** maintainability
- **Location:** `tickets/store.py:65`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The method constructs the query using an f‑string instead of bound parameters, which conflicts with the project's requirement to use parameter binding for all SQL.)

> The new `search_assignee` method builds its SQL query using an f‑string, directly interpolating the user‑provided `name` value, which violates the rule that all SQL must use bound parameters.

**Evidence**

From code:

```
query = f"SELECT * FROM tickets WHERE LOWER(assignee) = '{name.lower()}' ORDER BY id"
```

From rules:

```
All SQL uses bound parameters (`?`). Never build SQL with f-strings, `%` or `+`.
```

### 4. [LOW] Rule: Public functions have type hints and a one-line docstring that says what they return or raise.

- **Category:** maintainability
- **Location:** `tickets/store.py:64`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The public function `search_assignee` has type hints but no docstring describing its return value or possible exceptions.)

> The newly added public method `search_assignee` has type hints but lacks a docstring describing its return value or possible exceptions, violating the documentation rule.

**Evidence**

From code:

```
def search_assignee(self, name: str) -> list[Ticket]:
```

From rules:

```
Public functions have type hints and a one-line docstring that says what they return or raise.
```

_1 duplicate finding(s) merged into another finding._
