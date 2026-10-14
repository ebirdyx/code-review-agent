# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#5, head `0d0a778a1e05c43e2194a590c7b05c1925095f28`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/5)
- **Case:** ebirdyx-ticket-system-demo-pr5-0d0a778
- **Ticket:** TS-5: Notify the assignee on assignment
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T01:49:25+00:00
- **Model time:** 12.5 s; tokens: 21473 in / 3959 out
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
| compliance | ok | 3.1 s | 4841 / 1055 | 1 candidate finding(s) |
| defects | ok | 2.9 s | 4236 / 795 | 1 candidate finding(s) |
| security | ok | 2.7 s | 4170 / 674 | 1 candidate finding(s) |
| standards | ok | 2.9 s | 4243 / 969 | 1 candidate finding(s) |
| verify | ok | 1.7 s | 3983 / 466 | 1 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: When a ticket is assigned, the new assignee is notified.

> The assign method calls the notifier with the assignee and a message after saving the ticket, and the test verifies that the notification is sent.

From code:

```
self.notifier(assignee, f"Ticket {ticket.id} was assigned to you: {ticket.title}")
```

From pr_description:

```
The new assignee is notified when a ticket is assigned.
```

### 2. MET: If the notification fails, the assignment still succeeds.

> The notifier call is wrapped in a try/except that swallows any exception, allowing the assignment to complete and return the ticket.

From code:

```
try:
                self.notifier(assignee, f"Ticket {ticket.id} was assigned to you: {ticket.title}")
            except Exception:
                pass
```

From code:

```
assert service.assign(ticket.id, "bob").assignee == "bob"
```

### 3. NOT MET: A failed notification is logged so that operators can see it.

> When the notification fails, the exception is silently ignored without any logging, so operators cannot see the failure.

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

> Try, Except, Pass detected. (reported by the static-analysis tool bandit, rule B110; a deterministic check, not a model's opinion). Also reported by ruff as error_handling: Do not catch blind exception: `Exception` (reported by the static-analysis tool ruff, rule BLE001; a deterministic check, not a model's opinion). Also reported by compliance as requirement_mismatch: When the notification fails, the exception is silently ignored without any logging, so operators cannot see the failure. Also reported by defects as error_handling: The ticket's acceptance criteria require that a failed notification is logged so operators can see it, but the code catches all exceptions from the notifier and silently discards them without any logging, violating the requirement and making failures invisible. Also reported by standards as maintainability: The assign method catches a generic Exception and silently passes, which violates the team rule that forbids silencing exceptions. Exceptions should be caught narrowly and either logged or re‑raised.

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

From ticket:

```
3. A failed notification is logged so that operators can see it.
```

From rules:

```
Never silence an exception: catch the narrowest type, and log or re-raise it. `except Exception: pass` is not allowed.
```

_4 duplicate finding(s) merged into another finding._

## Dismissed by verification

These candidates were judged unsupported by the verification pass. They are listed so nothing disappears silently; the human reviewer can overrule the verifier.

- **Missing authorization check on ticket assignment** (`tickets/service.py:39`, found by security): The code indeed lacks any permission check, but the provided ticket, PR description, and acceptance criteria do not specify that such a check is required, so the claim of a security issue is not supported by the given evidence.
