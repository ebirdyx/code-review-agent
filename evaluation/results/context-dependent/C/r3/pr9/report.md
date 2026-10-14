# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#9, head `4046476aaadb8b1d1981e644aa3bdc59af337088`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/9)
- **Case:** ebirdyx-ticket-system-demo-pr9-4046476
- **Ticket:** TS-9: Keep ticket titles exactly as typed
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T04:58:34+00:00
- **Model time:** 15.1 s; tokens: 18333 in / 5129 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 2 findings

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

1 file(s) changed, +1 / -2 lines (1 source, 0 test); file types: .py x1.
- 1 source file(s) changed but no test file changed.

## Repository context

Code outside the change that the model was shown, found by matching function names (it can match the wrong function).

- `TicketService.create_ticket` (tickets/service.py) is called by 0 other repository function(s) and mentioned in 5 test function(s).
- test of `TicketService.create_ticket`: tests/test_service.py:14-17 (`test_create_ticket_is_open_and_gets_an_id`)
- class of `TicketService.create_ticket`: tickets/service.py:17-18 (`TicketService.__init__`)
- callee of `TicketService.create_ticket`: tickets/store.py:30-40 (`TicketStore.add`)
- test of `TicketService.create_ticket`: tests/test_service.py:20-23 (`test_a_title_is_required`)
- test of `TicketService.create_ticket`: tests/test_service.py:26-29 (`test_title_length_limit_is_inclusive`)

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 1 | 0 | 0 |  |
| bandit 1.9.4 | ok | 1 | 0 | 0 |  |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 4.1 s | 4174 / 1356 | 0 candidate finding(s) |
| defects | ok | 2.6 s | 3569 / 875 | 1 candidate finding(s) |
| security | ok | 2.3 s | 3503 / 515 | 0 candidate finding(s) |
| standards | ok | 4.5 s | 3576 / 1618 | 1 candidate finding(s) |
| verify | ok | 2.3 s | 3511 / 765 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: A ticket's title is stored exactly as the user typed it, including surrounding spaces.

> The create_ticket method no longer strips whitespace from the title and stores the title exactly as received, satisfying the requirement to keep surrounding spaces.

From code:

```
def create_ticket(self, title: str, description: str, reporter: str, priority: Priority = Priority.MEDIUM) -> Ticket:
    """Create an open ticket. The title is kept exactly as typed; it is required and at most MAX_TITLE characters."""
    if not title:
        raise ValueError("a ticket needs a title")
    if len(title) > MAX_TITLE:
        raise ValueError(f"the title is longer than {MAX_TITLE} characters")
```

Where: `tickets/service.py:21`

### 2. CANNOT DETERMINE: A title is still required and is at most 120 characters.

> The ticket requires a title to be "required" and at most 120 characters, but does not define whether a title consisting only of whitespace satisfies the "required" condition. The code treats any non‑empty string (including whitespace‑only strings) as valid, so it is unclear if this meets the intended requirement.

From code:

```
if not title:
    raise ValueError("a ticket needs a title")
if len(title) > MAX_TITLE:
    raise ValueError(f"the title is longer than {MAX_TITLE} characters")
```

Where: `tickets/service.py:22`

## Findings

### 1. [MEDIUM] Title validation does not reject whitespace‑only strings

- **Category:** logic_defect
- **Location:** `tickets/service.py:22`
- **Location and quotes:** **NOT FULLY CONFIRMED**, see below
- **Found by:** defects
- **Verification:** supported (The code checks `if not title:` which does not reject whitespace‑only strings, yet the test expects a ValueError for such inputs, confirming the logic defect.)

> The function checks `if not title:` to enforce that a title is required. In Python a string containing only spaces is truthy, so titles consisting solely of whitespace bypass this check and are accepted, violating the requirement that a title must be provided (the tests expect a ValueError for such inputs). This leads to tickets with empty‑looking titles being created.

**Evidence**

From code:

```
if not title:
            raise ValueError("a ticket needs a title")
```

From ticket:

```
1. A ticket's title is stored exactly as the user typed it, including surrounding spaces.
2. A title is still required and is at most 120 characters.
```

From code:

```
def test_a_title_is_required(service, title):
    with pytest.raises(ValueError, match="needs a title"):
        service.create_ticket(title, "", "alice")
```

From code:

```
title = "   "
```

**Validation problems**

- `quote_not_found`: Quoted code text was not found in the input: "title = " ""

### 2. [LOW] Rule: public functions have type hints and a one-line docstring that says what they return or raise

- **Category:** maintainability
- **Location:** `tickets/service.py:21`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The public method `create_ticket` has a one‑line docstring that does not mention its return value or possible exceptions, violating the team rule requiring such documentation.)

> The `create_ticket` public method has a one-line docstring, but it does not mention what the function returns (a Ticket) or the exceptions it may raise, violating the team's documentation rule.

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

- The ticket does not specify whether a title consisting only of spaces satisfies the "required" condition, leading to ambiguity for criterion 2.
- The repository code for rendering or otherwise processing ticket titles (e.g., HTML templates, logs, or external APIs) is not provided, so we cannot assess whether storing titles with leading/trailing whitespace or without stripping could lead to injection or XSS vulnerabilities in downstream components.
