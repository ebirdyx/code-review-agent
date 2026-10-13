<!-- code-review-agent -->
## Automated code review

Reviewed commit `60559c2aa26af2ffe8c6ccc9751feffc69e96237` against ticket **TS-3: Search tickets by assignee**.

**4 finding(s)**

### Requirements

| # | Criterion | Verdict |
|--:|---|---|
| 1 | Tickets can be found by the name of their assignee. | MET |
| 2 | The match ignores upper and lower case. | MET |
| 3 | When nobody matches, the result is an empty list. | MET |

### Findings

1. **[HIGH]** bandit B608: Possible SQL injection vector through string-based query construction. — `tickets/store.py:65` (static analysis)
   Possible SQL injection vector through string-based query construction. (reported by the static-analysis tool bandit, rule B608; a deterministic check, not a model's opinion).
2. **[MEDIUM]** SQL query built with f-string allows injection or syntax errors on special characters — `tickets/store.py:65`
   The `search_assignee` method constructs the SQL statement using an f-string that directly interpolates the user‑provided `name` after calling `lower()`. If the name contains characters such as a single quote, the resulting query becomes syntactically invalid or could be exploited for SQL injection, causing the function to fail or return incorrect results. Proper parameter binding should be used to handle all input safely.
   _Second look: supported._
3. **[LOW]** Rule: All SQL uses bound parameters (`?`). Never build SQL with f-strings, `%` or `+`. — `tickets/store.py:65`
   The new `search_assignee` method builds its SQL query using an f‑string, directly interpolating the user‑provided `name` value, which violates the rule that all SQL must use bound parameters.
   _Second look: supported._
4. **[LOW]** Rule: Public functions have type hints and a one-line docstring that says what they return or raise. — `tickets/store.py:64`
   The newly added public method `search_assignee` has type hints but lacks a docstring describing its return value or possible exceptions, violating the documentation rule.
   _Second look: supported._

<details><summary>Evidence for the first finding</summary>

```
query = f"SELECT * FROM tickets WHERE LOWER(assignee) = '{name.lower()}' ORDER BY id"
```

</details>

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.