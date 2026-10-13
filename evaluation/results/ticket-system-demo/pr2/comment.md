<!-- code-review-agent -->
## Automated code review

Reviewed commit `2ad2b01eaa423cc125af1ff5b0df8781230c15a0` against ticket **TS-2: Escalate stale tickets**.

**2 finding(s)**

### Requirements

| # | Criterion | Verdict |
|--:|---|---|
| 1 | An open ticket that has existed for 48 hours or more is raised by one priority level. | NOT MET |
| 2 | An urgent ticket stays urgent. | MET |
| 3 | Tickets that are not open (in progress, resolved, closed) are never escalated. | MET |

### Findings

1. **[HIGH]** Escalation condition excludes tickets exactly 48 hours old — `tickets/service.py:50`
   The acceptance criteria require tickets that have existed for 48 hours or more to be escalated. The implementation uses a strict greater-than comparison (`> ESCALATION_AGE`), which skips tickets that are exactly 48 hours old, violating the boundary condition.
   _Second look: supported._
2. **[LOW]** Rule: every change in behaviour comes with a test, including the boundary values (for example "exactly 48 hours") — `tests/test_service.py (no line given)`
   The new escalation functionality is added, but the test suite does not include a test for the exact 48‑hour boundary, which the team rule requires for any behavioural change.
   _Second look: supported._

<details><summary>Evidence for the first finding</summary>

```
if now - ticket.created_at > ESCALATION_AGE:
```

</details>

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.