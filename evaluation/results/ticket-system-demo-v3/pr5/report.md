# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#5, head `0d0a778a1e05c43e2194a590c7b05c1925095f28`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/5)
- **Case:** ebirdyx-ticket-system-demo-pr5-0d0a778
- **Ticket:** TS-5: Notify the assignee on assignment
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v3
- **Date (UTC):** 2026-10-13T23:54:57+00:00
- **Model time:** 13.5 s; tokens: 20771 in / 3954 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 1 finding

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

2 file(s) changed, +27 / -1 lines (1 source, 1 test); file types: .py x2.

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 2 | 1 | 1 |  |
| bandit 1.9.4 | ok | 2 | 1 | 1 | 8 warning(s) in test files were ignored (noise in tests) |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 4.8 s | 4702 / 1225 | 1 candidate finding(s) |
| defects | ok | 3.2 s | 4097 / 1014 | 1 candidate finding(s) |
| security | ok | 2.2 s | 4031 / 607 | 1 candidate finding(s) |
| standards | ok | 2.1 s | 4104 / 605 | 1 candidate finding(s) |
| verify | ok | 2.0 s | 3837 / 503 | 1 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: When a ticket is assigned, the new assignee is notified.

> The assign method calls the provided notifier with the assignee and a message after setting the assignee, satisfying the requirement to notify the new assignee.

From code:

```
self.notifier(assignee, f"Ticket {ticket.id} was assigned to you: {ticket.title}")
```

Where: `tickets/service.py:44`

### 2. MET: If the notification fails, the assignment still succeeds.

> The notifier call is wrapped in a try/except that catches any exception and allows the method to continue, so a notification failure does not prevent the assignment from succeeding.

From code:

```
except Exception:
                pass
```

Where: `tickets/service.py:45`

### 3. NOT MET: A failed notification is logged so that operators can see it.

> When the notification fails, the exception is silently ignored without any logging, so operators cannot see that the notification failed, violating the requirement to log failed notifications.

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
- **Found by:** ruff, bandit, compliance, defects, standards
- **Backed by:** a static-analysis tool (a deterministic check, not put to the verifier's vote)

> Try, Except, Pass detected. (reported by the static-analysis tool bandit, rule B110; a deterministic check, not a model's opinion). Also reported by ruff as error_handling: Do not catch blind exception: `Exception` (reported by the static-analysis tool ruff, rule BLE001; a deterministic check, not a model's opinion). Also reported by compliance as requirement_mismatch: When the notification fails, the exception is silently ignored without any logging, so operators cannot see that the notification failed, violating the requirement to log failed notifications. Also reported by defects as error_handling: When the notifier raises an exception, the code catches the exception and silently passes, but it does not log the failure. The acceptance criteria require that a failed notification be logged so operators can see it. The missing logging means the failure is invisible, violating the requirement and making debugging harder. Also reported by standards as maintainability: The code catches a broad `Exception` and silently passes, which violates the team rule that forbids silencing exceptions. Exceptions should be caught narrowly and either logged or re‑raised.

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

From code:

```
if self.notifier:
            try:
                self.notifier(assignee, f"Ticket {ticket.id} was assigned to you: {ticket.title}")
            except Exception:
                pass
```

From rules:

```
Never silence an exception: catch the narrowest type, and log or re-raise it. `except Exception: pass` is not allowed.
```

_4 duplicate finding(s) merged into another finding._

## Dismissed by verification

These candidates were judged unsupported by the verification pass. They are listed so nothing disappears silently; the human reviewer can overrule the verifier.

- **Missing authorization check on ticket assignment** (`tickets/service.py:39`, found by security): The code indeed lacks an explicit authorization check, but no requirement or rule in the provided ticket, PR description, or team rules mandates such a check for assignment, so the claim is not substantiated by the given evidence.
