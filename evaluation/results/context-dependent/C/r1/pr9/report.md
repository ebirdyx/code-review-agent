# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#9, head `4046476aaadb8b1d1981e644aa3bdc59af337088`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/9)
- **Case:** ebirdyx-ticket-system-demo-pr9-4046476
- **Ticket:** TS-9: Keep ticket titles exactly as typed
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T04:54:14+00:00
- **Model time:** 18.0 s; tokens: 18257 in / 4795 out
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
| compliance | ok | 4.4 s | 4174 / 1292 | 0 candidate finding(s) |
| defects | ok | 4.0 s | 3569 / 943 | 0 candidate finding(s) |
| security | ok | 2.1 s | 3503 / 449 | 0 candidate finding(s) |
| standards | ok | 5.4 s | 3576 / 1418 | 2 candidate finding(s) |
| verify | ok | 2.9 s | 3435 / 693 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: A ticket's title is stored exactly as the user typed it, including surrounding spaces.

> The create_ticket method no longer strips the title and passes it directly to the Ticket object, preserving any surrounding spaces exactly as typed.

From code:

```
"""Create an open ticket. The title is kept exactly as typed; it is required and at most MAX_TITLE characters."""
```

From code:

```
return self.store.add(Ticket(id=0, title=title, description=description, reporter=reporter, priority=priority))
```

Where: `tickets/service.py`

### 2. MET: A title is still required and is at most 120 characters.

> The method checks that the title is non‑empty (truthy) and that its length does not exceed MAX_TITLE (120), satisfying the requirement that a title is required and at most 120 characters.

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

Where: `tickets/service.py`

## Findings

### 1. [LOW] Rule 3: docstring does not state return or raise

- **Category:** maintainability
- **Location:** `tickets/service.py:21`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The docstring for the public method `create_ticket` does not mention its return value or possible exceptions, violating Team Rule 3 which requires a one-line docstring stating what the function returns or raises.)

> The public method `create_ticket` has a one-line docstring, but it does not explicitly state what the function returns or which exceptions it may raise, violating the rule that public functions must have a docstring that says what they return or raise.

**Evidence**

From code:

```
"Create an open ticket. The title is kept exactly as typed; it is required and at most MAX_TITLE characters."
```

From rules:

```
3. Public functions have type hints and a one-line docstring that says what they return or raise.
```

### 2. [LOW] Rule 4: behavior change lacks corresponding test

- **Category:** maintainability
- **Location:** `tests/test_service.py:15`
- **Location and quotes:** **NOT FULLY CONFIRMED**, see below
- **Found by:** standards
- **Verification:** supported (The change removes title stripping, altering observable behavior, but the existing test still expects the stripped title and no new test covering the new behavior is present, violating Team Rule 4 that every behavior change must have a test.)

> The change removes the stripping of whitespace from the title, altering the observable behavior. No new test is provided to verify the new behavior, and an existing test still expects the old stripped title, indicating a missing or outdated test for the changed behavior.

**Evidence**

From code:

```
assert ticket.title == "Printer is broken"
```

From rules:

```
4. Every change in behaviour comes with a test, including the boundary values (for example "exactly 48 hours").
```

**Validation problems**

- `quote_not_found`: Quoted code text was not found in the input: "assert ticket.title == "Printer is broken""

## Limitations stated by the model

- The acceptance criteria do not specify whether a title consisting only of whitespace should be considered invalid; the code now accepts such titles, but related tests expect them to be rejected.
- The provided code does not show how ticket titles are later rendered or processed (e.g., in HTML templates, logs, or external APIs), so potential injection or output encoding issues cannot be fully assessed.
