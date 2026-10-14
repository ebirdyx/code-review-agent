# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#9, head `4046476aaadb8b1d1981e644aa3bdc59af337088`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/9)
- **Case:** ebirdyx-ticket-system-demo-pr9-4046476
- **Ticket:** TS-9: Keep ticket titles exactly as typed
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T04:56:21+00:00
- **Model time:** 20.4 s; tokens: 18603 in / 5513 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 4 findings

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
| compliance | ok | 5.6 s | 4174 / 1271 | 0 candidate finding(s) |
| defects | ok | 5.0 s | 3569 / 1249 | 1 candidate finding(s) |
| security | ok | 3.3 s | 3503 / 821 | 1 candidate finding(s) |
| standards | ok | 3.9 s | 3576 / 1229 | 2 candidate finding(s) |
| verify | ok | 3.3 s | 3781 / 943 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: A ticket's title is stored exactly as the user typed it, including surrounding spaces.

> The create_ticket method no longer strips whitespace and stores the title exactly as received, satisfying the requirement to keep surrounding spaces.

From code:

```
"Create an open ticket. The title is kept exactly as typed; it is required and at most MAX_TITLE characters."
```

From code:

```
return self.store.add(Ticket(id=0, title=title, description=description, reporter=reporter, priority=priority))
```

Where: `tickets/service.py:21`

### 2. MET: A title is still required and is at most 120 characters.

> The method checks that the title is non‑empty and that its length does not exceed MAX_TITLE (120), fulfilling the required and length constraints.

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

**Validation problems**

- `inconsistent_verdict`: Marked met, but finding 1 ('Whitespace-only titles are accepted as valid') reports a problem in the code this verdict cites. Check this verdict yourself.

## Findings

### 1. [MEDIUM] Whitespace-only titles are accepted as valid

- **Category:** logic_defect
- **Location:** `tickets/service.py:22`
- **Location and quotes:** checked against the input
- **Found by:** defects
- **Verification:** supported (The code only checks `if not title:` which treats whitespace‑only strings as valid, so such titles bypass the required‑title validation.)

> The requirement states that a title is required, but the code only checks `if not title:` which treats any non‑empty string (including strings that contain only spaces) as valid. After removing the previous `title = title.strip()`, whitespace‑only titles bypass the validation, violating the "title is required" rule and causing tests that expect a ValueError for such inputs to fail.

**Evidence**

From code:

```
if not title:
    raise ValueError("a ticket needs a title")
```

From ticket:

```
A title is still required and is at most 120 characters.
```

### 2. [MEDIUM] Potential stored XSS via unsanitized ticket title

- **Category:** security
- **Location:** `tickets/service.py:22`
- **Location and quotes:** checked against the input
- **Found by:** security
- **Verification:** uncertain (No evidence is provided about how titles are rendered, so we cannot determine whether storing unsanitized titles leads to XSS.)

> The title is now stored exactly as typed without stripping or sanitizing, allowing malicious HTML/JS payloads to be saved and later rendered, leading to stored cross‑site scripting if the title is displayed in a web page without proper escaping.

**Evidence**

From code:

```
def create_ticket(self, title: str, description: str, reporter: str, priority: Priority = Priority.MEDIUM) -> Ticket:
        """Create an open ticket. The title is kept exactly as typed; it is required and at most MAX_TITLE characters."""
        if not title:
            raise ValueError("a ticket needs a title")
        if len(title) > MAX_TITLE:
            raise ValueError(f"the title is longer than {MAX_TITLE} characters")
        return self.store.add(Ticket(id=0, title=title, description=description, reporter=reporter, priority=priority))
```

### 3. [LOW] Rule: public functions must have docstring stating return or raise

- **Category:** maintainability
- **Location:** `tickets/service.py:21`
- **Location and quotes:** checked against the input
- **Found by:** standards
- **Verification:** supported (The public method `create_ticket` has a one‑line docstring that does not mention its return value or raised exceptions, violating the team rule.)

> The public method `create_ticket` has a one‑line docstring, but it does not mention what the function returns (a `Ticket`) or what exceptions it may raise. This violates the team rule requiring docstrings to state return values or raised exceptions.

**Evidence**

From code:

```
"""Create an open ticket. The title is kept exactly as typed; it is required and at most MAX_TITLE characters."""
```

From rules:

```
Public functions have type hints and a one-line docstring that says what they return or raise.
```

### 4. [LOW] Rule: every change in behaviour must be accompanied by a test

- **Category:** maintainability
- **Location:** `tickets/service.py (no line given)`
- **Location and quotes:** **NOT FULLY CONFIRMED**, see below
- **Found by:** standards
- **Verification:** supported (Removing `title = title.strip()` changes behavior, but existing tests still expect stripped titles, indicating no new test was added for the change.)

> The change removes the `title = title.strip()` line, altering the behaviour of `create_ticket` (titles are no longer stripped). Existing tests still expect stripped titles, and no new test was added to cover the new behaviour, violating the rule that every behavioural change must have a test.

**Evidence**

From code:

```
-        title = title.strip()
```

From rules:

```
Every change in behaviour comes with a test, including the boundary values (for example "exactly 48 hours").
```

**Validation problems**

- `quote_not_found`: Quoted code text was not found in the input: "- title = title.strip()"

## Limitations stated by the model

- The review cannot see how ticket titles are later rendered; the XSS risk depends on downstream HTML handling which is not provided.
