# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#5, head `0d0a778a1e05c43e2194a590c7b05c1925095f28`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/5)
- **Case:** ebirdyx-ticket-system-demo-pr5-0d0a778
- **Ticket:** TS-5: Notify the assignee on assignment
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T01:47:09+00:00
- **Model time:** 14.7 s; tokens: 24328 in / 4099 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 2 findings

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

2 file(s) changed, +27 / -1 lines (1 source, 1 test); file types: .py x2.

## Repository context

Code outside the change that the model was shown, found by matching function names (it can match the wrong function).

- `TicketService.assign` (tickets/service.py) is called by 0 other repository function(s) and mentioned in 3 test function(s) (2 added or changed by this change).
- `TicketService.__init__` (tickets/service.py) is called by 0 other repository function(s) and mentioned in 3 test function(s) (2 added or changed by this change).
- test of `TicketService.assign`: tests/test_service.py:32-35 (`test_assign_persists`)
- test of `TicketService.__init__`: tests/test_service.py:9-11 (`service`)
- callee of `TicketService.assign`: tickets/service.py:32-36 (`TicketService.get`)
- callee of `TicketService.assign`: tickets/store.py:42-44 (`TicketStore.get`)
- callee of `TicketService.assign`: tickets/store.py:46-51 (`TicketStore.save`)

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 2 | 1 | 1 |  |
| bandit 1.9.4 | ok | 2 | 1 | 1 | 8 warning(s) in test files were ignored (noise in tests) |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 4.2 s | 5419 / 1238 | 1 candidate finding(s) |
| defects | ok | 4.3 s | 4814 / 1196 | 1 candidate finding(s) |
| security | ok | 2.9 s | 4748 / 525 | 0 candidate finding(s) |
| standards | ok | 2.4 s | 4821 / 814 | 1 candidate finding(s) |
| verify | ok | 1.6 s | 4526 / 326 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: When a ticket is assigned, the new assignee is notified.

> The assign method calls the notifier when a notifier is provided, and the test verifies that a notification is sent after assignment.

From code:

```
self.notifier(assignee, f"Ticket {ticket.id} was assigned to you: {ticket.title}")
```

From code:

```
assert sent == [("bob", f"Ticket {ticket.id} was assigned to you: Printer jams")]
```

Where: `tickets/service.py:44`

### 2. MET: If the notification fails, the assignment still succeeds.

> The assign method catches any exception from the notifier and still returns the ticket with the new assignee, as confirmed by the test that simulates a failing notifier.

From code:

```
except Exception:
                pass
```

From code:

```
assert service.assign(ticket.id, "bob").assignee == "bob"
```

Where: `tickets/service.py:45`

### 3. NOT MET: A failed notification is logged so that operators can see it.

> The code silently swallows notification failures without logging them, so a failed notification is not recorded for operators.

From ticket:

```
A failed notification is logged so that operators can see it.
```

From code:

```
except Exception:
                pass
```

Where: `tickets/service.py:45`

## Findings

### 1. [MEDIUM] bandit B110: Try, Except, Pass detected.

- **Category:** security
- **Location:** `tickets/service.py:45`
- **Location and quotes:** checked against the input
- **Found by:** ruff, bandit, compliance, standards
- **Backed by:** a static-analysis tool (a deterministic check, not put to the verifier's vote)

> Try, Except, Pass detected. (reported by the static-analysis tool bandit, rule B110; a deterministic check, not a model's opinion). Also reported by ruff as error_handling: Do not catch blind exception: `Exception` (reported by the static-analysis tool ruff, rule BLE001; a deterministic check, not a model's opinion). Also reported by compliance as requirement_mismatch: The code silently swallows notification failures without logging them, so a failed notification is not recorded for operators. Also reported by standards as maintainability: The code catches a broad Exception and silently ignores it with pass, violating the team rule that exceptions must not be silenced.

**Evidence**

From code:

```
except Exception:
```

From ticket:

```
A failed notification is logged so that operators can see it.
```

From code:

```
except Exception:
                pass
```

From rules:

```
Never silence an exception: catch the narrowest type, and log or re-raise it. `except Exception: pass` is not allowed.
```

### 2. [MEDIUM] Failed notification is silently ignored without logging

- **Category:** error_handling
- **Location:** `tickets/service.py:42`
- **Location and quotes:** checked against the input
- **Found by:** defects
- **Verification:** supported (The assign method catches any Exception from the notifier and does a bare `pass` without logging, while the ticket acceptance criteria require that a failed notification be logged for operators.)

> When the notifier raises an exception, the code catches a broad Exception and does nothing (`pass`). The ticket's acceptance criteria require that a failed notification be logged so operators can see it. Swallowing the exception without logging hides the failure and makes debugging impossible.

**Evidence**

From code:

```
if self.notifier:
    try:
        self.notifier(assignee, f"Ticket {ticket.id} was assigned to you: {ticket.title}")
    except Exception:
        pass
```

From ticket:

```
A failed notification is logged so that operators can see it.
```

_3 duplicate finding(s) merged into another finding._

## Limitations stated by the model

- The security impact of the provided notifier callable cannot be fully assessed without seeing its implementation; if it performs unsafe operations with the message containing user-controlled ticket.title, potential injection risks could exist.
