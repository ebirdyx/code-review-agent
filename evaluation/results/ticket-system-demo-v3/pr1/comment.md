<!-- code-review-agent -->
## Automated code review

Reviewed commit `cdc6d0b435f351dcbe672c331bbda655bf4efc7c` against ticket **TS-1: Comments on tickets**.

**3 finding(s)**

### Requirements

| # | Criterion | Verdict |
|--:|---|---|
| 1 | Any user can add a comment to an existing ticket. | MET |
| 2 | An empty or whitespace-only comment is rejected. | MET |
| 3 | A comment is at most 2000 characters. | MET |
| 4 | A ticket's comments are listed oldest first. | MET |

### Findings

1. **[MEDIUM]** add_comment does not verify ticket existence — `tickets/store.py:76`
   The store's add_comment method inserts a comment row without checking that the referenced ticket_id exists. If called directly (bypassing TicketService), it can create orphan comments, violating data integrity.
   _Second look: supported._
2. **[LOW]** Rule: Public functions have type hints and a one-line docstring that says what they return or raise — `tickets/service.py:43`
   The public method `add_comment` has a type hint but its one-line docstring mentions only the raised exception and does not state what the function returns, violating the rule that docstrings must say what they return or raise.
   _Second look: supported._
3. **[LOW]** Rule: Public functions have type hints and a one-line docstring that says what they return or raise — `tickets/store.py:87`
   The public method `list_comments` has a type hint but its docstring does not specify the return value, violating the rule that docstrings must indicate what they return or raise.
   _Second look: supported._

<details><summary>Evidence for the first finding</summary>

```
def add_comment(self, comment: Comment) -> Comment:
        """Insert a comment and return it with its new id."""
        cursor = self._db.execute(
            "INSERT INTO comments (ticket_id, author, body, created_at) VALUES (?, ?, ?, ?)",
            (comment.ticket_id, comment.author, comment.body, comment.created_at.isoformat()),
        )
```

</details>

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.