<!-- code-review-agent -->
## Automated code review

Reviewed commit `6d474ad63768ec95c6216d77cee949006b91b220` against ticket **TS-4: Restrict who can resolve a ticket**.

**3 finding(s)**

### Requirements

| # | Criterion | Verdict |
|--:|---|---|
| 1 | Only the assignee or an administrator can resolve a ticket. | NOT MET |
| 2 | Anyone else who tries gets a PermissionError and the ticket is unchanged. | MET |
| 3 | Resolving follows the normal workflow (a ticket must be in progress first). | MET |

### Findings

1. **[HIGH]** Criterion 1 not met: Only the assignee or an administrator can resolve a ticket. — `tickets/service.py:41`
   The resolve method allows the reporter to resolve a ticket and does not check the admins set, violating the requirement that only the assignee or an administrator may resolve.
   _Second look: supported._
2. **[HIGH]** Reporter allowed to resolve tickets — `tickets/service.py:44`
   The resolve method permits the ticket reporter to resolve a ticket (actor == ticket.reporter) which violates the acceptance criteria that only the assignee or an administrator may resolve a ticket. This can let unauthorized users close tickets.
   _Second look: supported._
3. **[MEDIUM]** Reporter allowed to resolve tickets, bypassing intended permission model — `tickets/service.py:44`
   The resolve method authorizes a user if they are the ticket's assignee OR the reporter, but the ticket's acceptance criteria require only the assignee or an administrator to resolve; this permits reporters to resolve tickets they should not be able to, creating an unauthorized action.
   _Second look: supported._

<details><summary>Evidence for the first finding</summary>

```
def resolve(self, ticket_id: int, actor: str, admins: frozenset[str] = frozenset()) -> Ticket:
    """Mark a ticket resolved. Raises PermissionError if `actor` is not allowed to."""
    ticket = self.get(ticket_id)
    if actor != ticket.assignee and actor != ticket.reporter:
        raise PermissionError(f"{actor} cannot resolve ticket {ticket_id}")
```

</details>

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.