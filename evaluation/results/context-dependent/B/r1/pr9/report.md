# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#9, head `4046476aaadb8b1d1981e644aa3bdc59af337088`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/9)
- **Case:** ebirdyx-ticket-system-demo-pr9-4046476
- **Ticket:** TS-9: Keep ticket titles exactly as typed
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T04:53:12+00:00
- **Model time:** 12.2 s; tokens: 15226 in / 4008 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 2 findings

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

1 file(s) changed, +1 / -2 lines (1 source, 0 test); file types: .py x1.
- 1 source file(s) changed but no test file changed.

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 1 | 0 | 0 |  |
| bandit 1.9.4 | ok | 1 | 0 | 0 |  |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 2.7 s | 3571 / 895 | 0 candidate finding(s) |
| defects | ok | 3.2 s | 2966 / 909 | 1 candidate finding(s) |
| security | ok | 1.7 s | 2900 / 370 | 0 candidate finding(s) |
| standards | ok | 2.9 s | 2973 / 894 | 1 candidate finding(s) |
| verify | ok | 2.3 s | 2816 / 940 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: A ticket's title is stored exactly as the user typed it, including surrounding spaces.

> The code no longer strips surrounding spaces from the title and stores the title directly in the Ticket object, preserving the exact user input.

From code:

```
title = title.strip()
```

From code:

```
return self.store.add(Ticket(id=0, title=title, description=description, reporter=reporter, priority=priority))
```

Where: `tickets/service.py:22`

**Validation problems**

- `inconsistent_verdict`: Marked met, but finding 1 ('Whitespace-only titles are accepted as valid') reports a problem in the code this verdict cites. Check this verdict yourself.

### 2. MET: A title is still required and is at most 120 characters.

> The function checks that the title is non‑empty and that its length does not exceed MAX_TITLE (120).

From code:

```
if not title:
    raise ValueError("a ticket needs a title")
```

From code:

```
if len(title) > MAX_TITLE:
    raise ValueError(f"the title is longer than {MAX_TITLE} characters")
```

Where: `tickets/service.py:24`

**Validation problems**

- `inconsistent_verdict`: Marked met, but finding 1 ('Whitespace-only titles are accepted as valid') reports a problem in the code this verdict cites. Check this verdict yourself.

## Findings

### 1. [MEDIUM] Whitespace-only titles are accepted as valid

- **Category:** boundary_condition
- **Location:** `tickets/service.py:22`
- **Location and quotes:** **NOT FULLY CONFIRMED**, see below
- **Found by:** defects
- **Verification:** uncertain (The code now accepts whitespace-only titles, but the ticket's acceptance criteria do not explicitly forbid such titles, so it is unclear whether this violates the "title is required" constraint.)

> The function now checks `if not title:` to enforce a required title, but it no longer strips surrounding whitespace. A title consisting only of spaces (e.g., " ") is non‑empty, so it passes the required check and is stored, effectively allowing an empty‑looking title. This may violate the intended "title is required" constraint.

**Evidence**

From code:

```
if not title:
    raise ValueError("a ticket needs a title")
```

From code:

```
-        title = title.strip()
```

**Validation problems**

- `quote_not_found`: Quoted code text was not found in the input: "- title = title.strip()"

### 2. [LOW] Rule: public functions docstring must state return or raise

- **Category:** maintainability
- **Location:** `tickets/service.py:21`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The public method `create_ticket` has a one-line docstring that does not mention its return value or the ValueError it may raise, violating the team rule requiring docstrings to state what they return or raise.)

> The public method `create_ticket` has a one-line docstring, but it does not mention what the function returns (a Ticket) or the exceptions it may raise (ValueError). This violates the team rule that public functions must have a one-line docstring that says what they return or raise.

**Evidence**

From code:

```
"""Create an open ticket. The title is kept exactly as typed; it is required and at most MAX_TITLE characters."""
```

From rules:

```
Public functions have type hints and a one-line docstring that says what they return or raise.
```

## Limitations stated by the model

- The ticket acceptance criteria do not explicitly state whether a title containing only whitespace should be rejected; the finding assumes that "required" implies non‑whitespace content.
- The provided code does not show how the ticket title is later used (e.g., in SQL queries, HTML rendering, logging, or shell commands), so potential injection or other security impacts of storing the title verbatim cannot be fully assessed.
- Cannot verify whether a test covering the changed behaviour was added, as test files were not provided.
