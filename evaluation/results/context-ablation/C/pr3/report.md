# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#3, head `60559c2aa26af2ffe8c6ccc9751feffc69e96237`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/3)
- **Case:** ebirdyx-ticket-system-demo-pr3-60559c2
- **Ticket:** TS-3: Search tickets by assignee
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T01:46:26+00:00
- **Model time:** 13.0 s; tokens: 26051 in / 4628 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 2 findings

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

3 file(s) changed, +23 / -0 lines (2 source, 1 test); file types: .py x3.

## Repository context

Code outside the change that the model was shown, found by matching function names (it can match the wrong function).

- `TicketStore.search_assignee` (tickets/store.py) is called by 1 other repository function(s) and mentioned in no test function.
- `TicketService.find_by_assignee` (tickets/service.py) is called by 0 other repository function(s) and mentioned in 2 test function(s) (2 added or changed by this change).
- class of `TicketStore.search_assignee`: tickets/store.py:25-28 (`TicketStore.__init__`)
- class of `TicketService.find_by_assignee`: tickets/service.py:17-18 (`TicketService.__init__`)
- callee of `TicketStore.search_assignee`: tickets/store.py:70-75 (`_from_row`)

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 3 | 0 | 0 |  |
| bandit 1.9.4 | ok | 3 | 1 | 1 | 7 warning(s) in test files were ignored (noise in tests) |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 3.2 s | 5761 / 981 | 0 candidate finding(s) |
| defects | ok | 3.3 s | 5156 / 960 | 1 candidate finding(s) |
| security | ok | 2.6 s | 5090 / 933 | 1 candidate finding(s) |
| standards | ok | 3.2 s | 5163 / 1292 | 2 candidate finding(s) |
| verify | ok | 1.3 s | 4881 / 462 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: Tickets can be found by the name of their assignee.

> The service provides a `find_by_assignee` method that returns tickets matching the given assignee name.

From code:

```
def find_by_assignee(self, name: str) -> list[Ticket]:
    """Tickets assigned to `name` (case does not matter); empty if nobody matches."""
    return self.store.search_assignee(name.strip())
```

### 2. MET: The match ignores upper and lower case.

> The search query lower‑cases both the stored assignee and the input name, making the match case‑insensitive.

From code:

```
query = f"SELECT * FROM tickets WHERE LOWER(assignee) = '{name.lower()}' ORDER BY id"
```

### 3. MET: When nobody matches, the result is an empty list.

> When no ticket matches the assignee name, the SQL query returns no rows and the method returns an empty list, as verified by the test.

From code:

```
assert service.find_by_assignee("nobody") == []
```

## Findings

### 1. [HIGH] bandit B608: Possible SQL injection vector through string-based query construction.

- **Category:** security
- **Location:** `tickets/store.py:65`
- **Location and quotes:** checked against the input
- **Found by:** bandit, defects, security, standards
- **Backed by:** a static-analysis tool (a deterministic check, not put to the verifier's vote)

> Possible SQL injection vector through string-based query construction. (reported by the static-analysis tool bandit, rule B608; a deterministic check, not a model's opinion). Also reported by defects as boundary_condition: The `search_assignee` method constructs the SQL statement using an f-string that directly inserts the lower‑cased `name` value. If the provided name contains characters such as a single quote, the resulting query becomes syntactically invalid and will raise an exception, causing the function to fail for those edge‑case inputs. Also reported by standards as maintainability: The newly added `search_assignee` method constructs an SQL query using an f-string, which violates the rule that all SQL must use bound parameters.

**Evidence**

From code:

```
query = f"SELECT * FROM tickets WHERE LOWER(assignee) = '{name.lower()}' ORDER BY id"
```

From code:

```
return self.store.search_assignee(name.strip())
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
- **Verification:** supported (The added public method `search_assignee` has type hints but no docstring, violating the rule that public functions must have a one-line docstring describing their return or raise.)

> The newly added public method `search_assignee` has type hints but lacks a one-line docstring describing its return value, violating the documentation rule.

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
