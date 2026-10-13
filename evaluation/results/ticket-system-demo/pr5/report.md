# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#5, head `0d0a778a1e05c43e2194a590c7b05c1925095f28`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/5)
- **Case:** ebirdyx-ticket-system-demo-pr5-0d0a778
- **Ticket:** TS-5: Notify the assignee on assignment
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v2
- **Date (UTC):** 2026-10-13T23:02:51+00:00
- **Model time:** 20.3 s; tokens: 20446 in / 4844 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 4 findings

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
| compliance | ok | 4.2 s | 4545 / 1138 | 1 candidate finding(s) |
| defects | ok | 4.3 s | 4097 / 863 | 1 candidate finding(s) |
| security | ok | 2.8 s | 4031 / 438 | 0 candidate finding(s) |
| standards | ok | 5.2 s | 3969 / 1349 | 2 candidate finding(s) |
| verify | ok | 4.7 s | 3804 / 1056 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: When a ticket is assigned, the new assignee is notified.

> The assign method calls the injected notifier with the assignee and a message, and the test verifies that the notification is sent.

From code:

```
self.notifier(assignee, f"Ticket {ticket.id} was assigned to you: {ticket.title}")
```

From pr_description:

```
The new assignee is notified when a ticket is assigned.
```

From code:

```
assert sent == [("bob", f"Ticket {ticket.id} was assigned to you: Printer jams")]
```

Where: `tickets/service.py:44`

### 2. MET: If the notification fails, the assignment still succeeds.

> The assign method catches any exception from the notifier and still returns the ticket, and the test confirms that assignment succeeds even when the notifier raises.

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

> The ticket requires that a failed notification be logged, but the code silently swallows the exception without any logging.

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

### 1. [MEDIUM] ruff BLE001: Do not catch blind exception: `Exception`

- **Category:** error_handling
- **Location:** `tickets/service.py:45`
- **Location and quotes:** checked against the input
- **Found by:** ruff, compliance, defects
- **Backed by:** a static-analysis tool (a deterministic check, not put to the verifier's vote)

> Do not catch blind exception: `Exception` (reported by the static-analysis tool ruff, rule BLE001; a deterministic check, not a model's opinion).

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
try:
                self.notifier(assignee, f"Ticket {ticket.id} was assigned to you: {ticket.title}")
            except Exception:
                pass
```

### 2. [LOW] bandit B110: Try, Except, Pass detected.

- **Category:** security
- **Location:** `tickets/service.py:45`
- **Location and quotes:** checked against the input
- **Found by:** bandit
- **Backed by:** a static-analysis tool (a deterministic check, not put to the verifier's vote)

> Try, Except, Pass detected. (reported by the static-analysis tool bandit, rule B110; a deterministic check, not a model's opinion).

**Evidence**

From code:

```
except Exception:
```

### 3. [LOW] Rule: Never silence an exception

- **Category:** maintainability
- **Location:** `tickets/service.py:45`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The code catches a broad `Exception` and silently ignores it with `pass` (lines 45-46), matching the claim.)

> The code catches a broad `Exception` and silently ignores it with `pass`, which violates the team rule that exceptions must not be silenced.

**Evidence**

From code:

```
except Exception:
    pass
```

From rules:

```
Never silence an exception: catch the narrowest type, and log or re-raise it. `except Exception: pass` is not allowed.
```

### 4. [LOW] Rule: Public functions need a docstring

- **Category:** maintainability
- **Location:** `tickets/service.py (no line given)`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The public method `assign` has type hints but no docstring (definition at line 39), confirming the claim.)

> The public method `assign` has type hints but lacks a one-line docstring describing its return value or raised exceptions, violating the team rule for public functions.

**Evidence**

From code:

```
def assign(self, ticket_id: int, assignee: str) -> Ticket:
```

From rules:

```
Public functions have type hints and a one-line docstring that says what they return or raise.
```

_2 duplicate finding(s) merged into another finding._
