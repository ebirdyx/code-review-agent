<!-- code-review-agent -->
## Automated code review

Reviewed commit `60559c2aa26af2ffe8c6ccc9751feffc69e96237` against ticket **TS-3: Search tickets by assignee**.

**3 finding(s)**

### Requirements

| # | Criterion | Verdict |
|--:|---|---|
| 1 | Tickets can be found by the name of their assignee. | MET (check: a finding disagrees) |
| 2 | The match ignores upper and lower case. | MET |
| 3 | When nobody matches, the result is an empty list. | MET |

### Findings

1. **[HIGH]** bandit B608: Possible SQL injection vector through string-based query construction. — `tickets/store.py:65` (static analysis)
   Possible SQL injection vector through string-based query construction. (reported by the static-analysis tool bandit, rule B608; a deterministic check, not a model's opinion). Also reported by standards as maintainability: The new method `search_assignee` builds an SQL query using an f‑string, which violates the rule that SQL must use bound parameters to avoid injection risks.
2. **[MEDIUM]** Whitespace in assignee names is not normalized, causing mismatched searches — `tickets/service.py:41`
   The `assign` method stores the assignee string as‑is, while `find_by_assignee` strips whitespace from the search term before querying. If an assignee is saved with leading or trailing spaces, a subsequent search for the same name (without spaces) will not match, leading to incorrect empty results.
   _Second look: supported._
3. **[LOW]** Rule: Public functions have a one-line docstring — `tickets/store.py:64`
   The newly added public method `search_assignee` lacks a docstring that describes its return value, violating the rule that public functions must have a one‑line docstring stating what they return or raise.
   _Second look: supported._

<details><summary>Evidence for the first finding</summary>

```
query = f"SELECT * FROM tickets WHERE LOWER(assignee) = '{name.lower()}' ORDER BY id"
```

</details>

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.