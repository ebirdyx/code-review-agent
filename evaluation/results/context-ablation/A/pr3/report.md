# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#3, head `60559c2aa26af2ffe8c6ccc9751feffc69e96237`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/3)
- **Case:** ebirdyx-ticket-system-demo-pr3-60559c2
- **Ticket:** TS-3: Search tickets by assignee
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T01:50:48+00:00
- **Model time:** 11.2 s; tokens: 23585 in / 4150 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 2 findings

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

3 file(s) changed, +23 / -0 lines (2 source, 1 test); file types: .py x3.

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 2.7 s | 5233 / 1168 | 0 candidate finding(s) |
| defects | ok | 2.9 s | 4628 / 1026 | 1 candidate finding(s) |
| security | ok | 2.4 s | 4562 / 722 | 1 candidate finding(s) |
| standards | ok | 2.3 s | 4635 / 821 | 1 candidate finding(s) |
| verify | ok | 1.6 s | 4527 / 413 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: Tickets can be found by the name of their assignee.

> TicketService.find_by_assignee delegates to TicketStore.search_assignee which queries tickets where the assignee matches the given name, thus tickets can be found by assignee name.

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

> The SQL query lower‑cases both the stored assignee and the supplied name, making the match case‑insensitive.

From code:

```
query = f"SELECT * FROM tickets WHERE LOWER(assignee) = '{name.lower()}' ORDER BY id"
```

Where: `tickets/store.py:64`

### 3. MET: When nobody matches, the result is an empty list.

> If no rows match, the list comprehension over an empty result set yields an empty list, satisfying the requirement for an empty result when nobody matches.

From code:

```
rows = self._db.execute(query).fetchall()
return [_from_row(r) for r in rows]
```

Where: `tickets/store.py:66`

## Findings

### 1. [HIGH] SQL injection via unparameterized query in search_assignee

- **Category:** security
- **Location:** `tickets/store.py:65`
- **Location and quotes:** checked against the input
- **Found by:** defects, security
- **Verification:** supported (The `search_assignee` method builds its SQL query with an f‑string that directly interpolates the user‑provided `name.lower()` value, creating an unparameterized query vulnerable to injection.)

> The `search_assignee` method builds an SQL query with an f-string that directly interpolates the user‑provided `name` value, allowing an attacker to inject arbitrary SQL (e.g., "bob' OR '1'='1") and retrieve or manipulate data beyond the intended assignee filter. Also reported by defects as logic_defect: The `search_assignee` method constructs the SQL statement using an f-string with the raw `name.lower()` value. If the provided name contains a single quote or other special characters, the resulting query will be malformed and raise a runtime SQLite error, breaking the function for such inputs.

**Evidence**

From code:

```
query = f"SELECT * FROM tickets WHERE LOWER(assignee) = '{name.lower()}' ORDER BY id"
```

### 2. [LOW] Rule: All SQL uses bound parameters

- **Category:** maintainability
- **Location:** `tickets/store.py:64`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The same f‑string query violates the team rule requiring all SQL to use bound parameters, thus the method breaches the coding rule.)

> The new `search_assignee` method builds its SQL query using an f-string, directly interpolating the user-provided `name` value. This violates the team rule that SQL must use bound parameters (`?`) and must not be constructed with f-strings, `%`, or `+`.

**Evidence**

From code:

```
query = f"SELECT * FROM tickets WHERE LOWER(assignee) = '{name.lower()}' ORDER BY id"
```

From rules:

```
All SQL uses bound parameters (`?`). Never build SQL with f-strings, `%` or `+`.
```

_1 duplicate finding(s) merged into another finding._
