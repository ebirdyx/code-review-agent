<!-- code-review-agent -->
## Automated code review

Reviewed commit `41791e15375771ff4d2504ca8e5d5069f947a340` against ticket **TS-6: Due dates and overdue tickets**.

**1 finding(s)**

### Requirements

| # | Criterion | Verdict |
|--:|---|---|
| 1 | A ticket can have an optional due date. | MET |
| 2 | Overdue tickets are flagged. | MET |

### Findings

1. **[LOW]** Rule: public functions must have a docstring that describes what they return or raise — `tickets/service.py:43`
   The newly added public method `set_due_date` has a one‑line docstring, but it does not mention the return value or any exceptions, violating the team rule that public functions' docstrings must state what they return or raise.
   _Second look: supported._

<details><summary>Evidence for the first finding</summary>

```
def set_due_date(self, ticket_id: int, due: date | None) -> Ticket:
    """Set or clear the due date of a ticket."""
    ticket = self.get(ticket_id)
    ticket.due_date = due
    self.store.save(ticket)
    return ticket
```

</details>

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.