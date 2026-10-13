# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#3, head `60559c2aa26af2ffe8c6ccc9751feffc69e96237`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/3)
- **Case:** ebirdyx-ticket-system-demo-pr3-60559c2
- **Ticket:** TS-3: Search tickets by assignee
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v3
- **Date (UTC):** 2026-10-13T23:53:19+00:00
- **Model time:** 15.7 s; tokens: 23523 in / 5125 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 3 findings

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
| compliance | ok | 3.6 s | 5221 / 1462 | 0 candidate finding(s) |
| defects | ok | 2.5 s | 4616 / 923 | 1 candidate finding(s) |
| security | ok | 1.8 s | 4550 / 601 | 1 candidate finding(s) |
| standards | ok | 5.3 s | 4623 / 1160 | 2 candidate finding(s) |
| verify | ok | 3.3 s | 4513 / 979 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: Tickets can be found by the name of their assignee.

> The service adds a `find_by_assignee` method that delegates to the store's `search_assignee` query, which returns tickets whose assignee matches the given name. The test `test_find_by_assignee_ignores_case` creates tickets, assigns them, and asserts that the method returns the correct ticket ID, confirming that tickets can be found by assignee name.

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

**Validation problems**

- `inconsistent_verdict`: Marked met, but finding 2 ('Whitespace in assignee names is not normalized, causing mismatched se…') reports a problem in the code this verdict cites. Check this verdict yourself.

### 2. MET: The match ignores upper and lower case.

> The SQL query in `search_assignee` compares `LOWER(assignee)` to the lower‑cased input name, ensuring the match ignores case. The corresponding test verifies that a mixed‑case query returns the correctly assigned ticket.

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

> When the search finds no matching assignee, the SQL returns no rows and the method returns an empty list. The test `test_find_by_assignee_returns_an_empty_list_when_nobody_matches` asserts that the result is `[]` for a non‑existent assignee.

From code:

```
assert service.find_by_assignee("nobody") == []
```

Where: `tests/test_service.py:62`

## Findings

### 1. [HIGH] bandit B608: Possible SQL injection vector through string-based query construction.

- **Category:** security
- **Location:** `tickets/store.py:65`
- **Location and quotes:** checked against the input
- **Found by:** bandit, security, standards
- **Backed by:** a static-analysis tool (a deterministic check, not put to the verifier's vote)

> Possible SQL injection vector through string-based query construction. (reported by the static-analysis tool bandit, rule B608; a deterministic check, not a model's opinion). Also reported by standards as maintainability: The new method `search_assignee` builds an SQL query using an f‑string, which violates the rule that SQL must use bound parameters to avoid injection risks.

**Evidence**

From code:

```
query = f"SELECT * FROM tickets WHERE LOWER(assignee) = '{name.lower()}' ORDER BY id"
```

From rules:

```
All SQL uses bound parameters (`?`). Never build SQL with f-strings, `%` or `+`.
```

### 2. [MEDIUM] Whitespace in assignee names is not normalized, causing mismatched searches

- **Category:** logic_defect
- **Location:** `tickets/service.py:41`
- **Location and quotes:** checked against the input
- **Found by:** defects
- **Verification:** supported (assign stores the assignee string unchanged while find_by_assignee strips whitespace from the search term, so a stored name with leading/trailing spaces will not match a stripped search.)

> The `assign` method stores the assignee string as‑is, while `find_by_assignee` strips whitespace from the search term before querying. If an assignee is saved with leading or trailing spaces, a subsequent search for the same name (without spaces) will not match, leading to incorrect empty results.

**Evidence**

From code:

```
def assign(self, ticket_id: int, assignee: str) -> Ticket:
        ticket = self.get(ticket_id)
        ticket.assignee = assignee
        self.store.save(ticket)
        return ticket
```

From code:

```
def find_by_assignee(self, name: str) -> list[Ticket]:
        """Tickets assigned to `name` (case does not matter); empty if nobody matches."""
        return self.store.search_assignee(name.strip())
```

### 3. [LOW] Rule: Public functions have a one-line docstring

- **Category:** maintainability
- **Location:** `tickets/store.py:64`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (search_assignee is a public method without any docstring, violating the team rule that public functions must have a one-line docstring describing return or raise.)

> The newly added public method `search_assignee` lacks a docstring that describes its return value, violating the rule that public functions must have a one‑line docstring stating what they return or raise.

**Evidence**

From code:

```
def search_assignee(self, name: str) -> list[Ticket]:
```

From rules:

```
Public functions have type hints and a one-line docstring that says what they return or raise.
```

_2 duplicate finding(s) merged into another finding._
