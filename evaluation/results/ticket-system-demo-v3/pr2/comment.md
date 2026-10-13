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

1. **[MEDIUM]** Escalation condition excludes tickets exactly 48 hours old — `tickets/service.py:50`
   The code uses a strict greater-than comparison (`now - ticket.created_at > ESCALATION_AGE`) to decide whether a ticket should be escalated. The acceptance criteria require tickets that are "48 hours or more" old to be escalated, so tickets that are exactly 48 hours old are incorrectly left unchanged. This off‑by‑one boundary can cause tickets to miss the required priority increase. Also reported by compliance as requirement_mismatch: The ticket requires escalation for tickets that have existed for 48 hours **or more**, but the implementation uses a strict greater‑than comparison (`&gt; ESCALATIO…
   _Second look: supported._
2. **[LOW]** Rule: test boundary value missing — `tests/test_service.py:64`
   The new behavior escalates tickets older than 48 hours, but the added tests do not include a test for the exact boundary value of 48 hours, violating the rule that every change in behaviour must be tested at its boundary values.
   _Second look: supported._

<details><summary>Evidence for the first finding</summary>

```
ESCALATION_AGE = timedelta(hours=48)
```

</details>

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.