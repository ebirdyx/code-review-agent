# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#9, head `4046476aaadb8b1d1981e644aa3bdc59af337088`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/9)
- **Case:** ebirdyx-ticket-system-demo-pr9-4046476
- **Ticket:** TS-9: Keep ticket titles exactly as typed
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T04:55:05+00:00
- **Model time:** 13.6 s; tokens: 15209 in / 3545 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 1 finding

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
| compliance | ok | 4.2 s | 3571 / 937 | 0 candidate finding(s) |
| defects | ok | 3.1 s | 2966 / 626 | 1 candidate finding(s) |
| security | ok | 2.2 s | 2900 / 455 | 0 candidate finding(s) |
| standards | ok | 2.5 s | 2973 / 888 | 1 candidate finding(s) |
| verify | ok | 2.2 s | 2799 / 639 | 1 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: A ticket's title is stored exactly as the user typed it, including surrounding spaces.

> The code no longer strips whitespace from the title and stores the title value directly in the Ticket object, preserving surrounding spaces as typed.

From code:

```
-        title = title.strip()
```

From code:

```
return self.store.add(Ticket(id=0, title=title, description=description, reporter=reporter, priority=priority))
```

Where: `tickets/service.py:21`

**Validation problems**

- `quote_not_found`: Quoted code text was not found in the input: "- title = title.strip()"

### 2. MET: A title is still required and is at most 120 characters.

> The function validates that a title is provided (non‑empty) and that its length does not exceed MAX_TITLE, which is defined as 120 characters.

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

Where: `tickets/service.py:22`

## Findings

### 1. [LOW] Rule: public functions docstring must state return or raise

- **Category:** maintainability
- **Location:** `tickets/service.py:21`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The team rule mandates that a public function's one‑line docstring state what it returns or raises, but the create_ticket docstring does not mention the returned Ticket or possible exceptions.)

> The public method `create_ticket` now has a one-line docstring, but it does not mention what the function returns (a Ticket) or what exceptions it may raise, violating the team rule that docstrings must say what they return or raise.

**Evidence**

From code:

```
"""Create an open ticket. The title is kept exactly as typed; it is required and at most MAX_TITLE characters."""
```

From rules:

```
Public functions have type hints and a one-line docstring that says what they return or raise.
```

## Dismissed by verification

These candidates were judged unsupported by the verification pass. They are listed so nothing disappears silently; the human reviewer can overrule the verifier.

- **Whitespace-only titles bypass required title check** (`tickets/service.py:22`, found by defects): The acceptance criteria require a title but allow storing it exactly as typed, including spaces, so whitespace‑only titles satisfy the "required" condition and the code correctly does not reject them.

## Limitations stated by the model

- The ticket description does not explicitly define whether a title consisting solely of whitespace satisfies the "title is required" rule, so the assessment assumes that a non‑empty string of spaces is not a valid title.
- The implementation of TicketStore.add and any downstream usage of the ticket title (e.g., in SQL queries or rendering) is not provided, so potential injection or other security issues related to storing raw titles cannot be fully assessed.
- Cannot verify compliance with rule 4 (tests for behavior changes) because test files were not provided.
