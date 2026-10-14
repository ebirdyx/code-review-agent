# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#9, head `4046476aaadb8b1d1981e644aa3bdc59af337088`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/9)
- **Case:** ebirdyx-ticket-system-demo-pr9-4046476
- **Ticket:** TS-9: Keep ticket titles exactly as typed
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T04:57:19+00:00
- **Model time:** 15.8 s; tokens: 15317 in / 4428 out
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
| compliance | ok | 2.9 s | 3571 / 896 | 0 candidate finding(s) |
| defects | ok | 3.4 s | 2966 / 802 | 1 candidate finding(s) |
| security | ok | 3.2 s | 2900 / 712 | 1 candidate finding(s) |
| standards | ok | 3.0 s | 2973 / 837 | 1 candidate finding(s) |
| verify | ok | 3.9 s | 2907 / 1181 | 1 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: A ticket's title is stored exactly as the user typed it, including surrounding spaces.

> The code no longer strips whitespace from the title and the docstring states the title is kept exactly as typed, so surrounding spaces are preserved when storing the ticket.

From code:

```
-        title = title.strip()
```

From code:

```
"""Create an open ticket. The title is kept exactly as typed; it is required and at most MAX_TITLE characters."""
```

Where: `tickets/service.py:21`

**Validation problems**

- `quote_not_found`: Quoted code text was not found in the input: "- title = title.strip()"

### 2. MET: A title is still required and is at most 120 characters.

> The function validates that a title is provided (non‑empty) and enforces a maximum length of 120 characters via MAX_TITLE.

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

From code:

```
MAX_TITLE = 120
```

Where: `tickets/service.py:22`

## Findings

### 1. [LOW] Whitespace-only titles bypass required check

- **Category:** security
- **Location:** `tickets/service.py:21`
- **Location and quotes:** checked against the input
- **Found by:** security
- **Verification:** uncertain (The claim about injection or log manipulation is speculative; the provided code shows no later use of the title that would confirm a security issue.)

> The removal of `title.strip()` means a title consisting only of spaces is considered non-empty by `if not title:` and will be stored, potentially allowing injection attacks or header/log manipulation if the title is later used in HTML, logs, or HTTP headers without further sanitization.

**Evidence**

From code:

```
title = title.strip()
```

From code:

```
if not title:
    raise ValueError("a ticket needs a title")
```

### 2. [LOW] Rule: Public functions have type hints and a one-line docstring that says what they return or raise

- **Category:** maintainability
- **Location:** `tickets/service.py:21`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (Team rule 3 requires a one‑line docstring describing return value or raised exceptions, but the create_ticket docstring is multi‑sentence and does not mention the returned Ticket or possible ValueError.)

> The docstring for the public method `create_ticket` does not mention what the function returns (a Ticket) or what exceptions it may raise, violating the team's rule that public functions must have a one-line docstring describing their return value or raised errors.

**Evidence**

From code:

```
"""Create an open ticket. The title is kept exactly as typed; it is required and at most MAX_TITLE characters."""
```

From rules:

```
3. Public functions have type hints and a one-line docstring that says what they return or raise.
```

## Dismissed by verification

These candidates were judged unsupported by the verification pass. They are listed so nothing disappears silently; the human reviewer can overrule the verifier.

- **Whitespace-only titles are accepted as valid** (`tickets/service.py:22`, found by defects): The ticket acceptance criteria only require a title to be stored as typed and be at most 120 characters; they do not forbid whitespace‑only titles, so accepting them does not violate the stated requirements.

## Limitations stated by the model

- The analysis cannot determine how the stored title is later used (e.g., in SQL queries, HTML rendering, logging), so the actual exploitability of whitespace-only titles is uncertain.
