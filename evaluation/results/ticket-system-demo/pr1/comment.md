<!-- code-review-agent -->
## Automated code review

Reviewed commit `cdc6d0b435f351dcbe672c331bbda655bf4efc7c` against ticket **TS-1: Comments on tickets**.

**2 finding(s)**

### Requirements

| # | Criterion | Verdict |
|--:|---|---|
| 1 | Any user can add a comment to an existing ticket. | MET |
| 2 | An empty or whitespace-only comment is rejected. | MET |
| 3 | A comment is at most 2000 characters. | MET |
| 4 | A ticket's comments are listed oldest first. | MET |

### Findings

1. **[LOW]** Rule: Public functions must have a docstring that says what they return or raise — `tickets/service.py:53`
   The public method `comments` has a one-line docstring that does not describe its return value, violating the rule that docstrings must state what the function returns or raises.
   _Second look: supported._
2. **[LOW]** Rule: Public functions must have a docstring that says what they return or raise — `tickets/store.py:88`
   The public method `list_comments` has a one-line docstring that does not describe its return value, violating the rule that docstrings must state what the function returns or raises.
   _Second look: supported._

<details><summary>Evidence for the first finding</summary>

```
"""Comments of a ticket, oldest first."""
```

</details>

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.