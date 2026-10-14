# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#3, head `60559c2aa26af2ffe8c6ccc9751feffc69e96237`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/3)
- **Case:** ebirdyx-ticket-system-demo-pr3-60559c2
- **Ticket:** TS-3: Search tickets by assignee
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T01:48:43+00:00
- **Model time:** 15.9 s; tokens: 24035 in / 5033 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 2 findings

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
| compliance | ok | 4.0 s | 5360 / 1235 | 0 candidate finding(s) |
| defects | ok | 3.8 s | 4755 / 1168 | 1 candidate finding(s) |
| security | ok | 2.6 s | 4689 / 639 | 1 candidate finding(s) |
| standards | ok | 4.9 s | 4762 / 1627 | 2 candidate finding(s) |
| verify | ok | 1.3 s | 4469 / 364 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: Tickets can be found by the name of their assignee.

> The service adds a `find_by_assignee` method that queries the store for tickets with the given assignee name, and a test confirms that a ticket can be retrieved by its assignee.

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

From code:

```
assert [t.id for t in service.find_by_assignee("bOb")] == [mine.id]
```

Where: `tickets/service.py:41`

### 2. MET: The match ignores upper and lower case.

> The search query lowercases both the stored assignee and the input name, making the match case‑insensitive, and the test verifies that different capitalizations are treated as equal.

From code:

```
query = f"SELECT * FROM tickets WHERE LOWER(assignee) = '{name.lower()}' ORDER BY id"
```

From code:

```
assert [t.id for t in service.find_by_assignee("bOb")] == [mine.id]
```

Where: `tickets/store.py:65`

### 3. MET: When nobody matches, the result is an empty list.

> When the search yields no rows, `search_assignee` returns an empty list, and the test asserts that calling `find_by_assignee` with a non‑existent name returns `[]`.

From code:

```
return [_from_row(r) for r in rows]
```

From code:

```
assert service.find_by_assignee("nobody") == []
```

Where: `tickets/store.py:67`

## Findings

### 1. [HIGH] bandit B608: Possible SQL injection vector through string-based query construction.

- **Category:** security
- **Location:** `tickets/store.py:65`
- **Location and quotes:** checked against the input
- **Found by:** bandit, defects, security, standards
- **Backed by:** a static-analysis tool (a deterministic check, not put to the verifier's vote)

> Possible SQL injection vector through string-based query construction. (reported by the static-analysis tool bandit, rule B608; a deterministic check, not a model's opinion). Also reported by defects as boundary_condition: The `search_assignee` method builds the SQL statement using an f-string with the raw lower‑cased name. If the provided name contains a single quote (or other SQL‑special characters), the resulting query becomes syntactically invalid, causing a runtime database error instead of returning an empty list. Also reported by standards as maintainability: The method `search_assignee` constructs an SQL query using an f‑string, which violates the rule that SQL must be built with bound parameters. This breaks the coding standard and can lead to injection issues.

**Evidence**

From code:

```
query = f"SELECT * FROM tickets WHERE LOWER(assignee) = '{name.lower()}' ORDER BY id"
```

From rules:

```
All SQL uses bound parameters (`?`). Never build SQL with f-strings, `%` or `+`.
```

### 2. [LOW] Rule: Public functions have type hints and a one-line docstring that says what they return or raise.

- **Category:** maintainability
- **Location:** `tickets/store.py:64`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The public method `search_assignee` in tickets/store.py has type hints but no docstring, violating the rule that public functions must include a one‑line docstring describing return or raised exceptions.)

> The public method `search_assignee` lacks a docstring, violating the rule that public functions must include a one‑line docstring describing the return value or raised exceptions.

**Evidence**

From code:

```
def search_assignee(self, name: str) -> list[Ticket]:
```

From rules:

```
Public functions have type hints and a one-line docstring that says what they return or raise.
```

_3 duplicate finding(s) merged into another finding._
