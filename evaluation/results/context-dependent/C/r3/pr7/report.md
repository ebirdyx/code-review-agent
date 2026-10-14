# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#7, head `a8fc214d01f07394b509d16ef58e2fcdf89d19b2`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/7)
- **Case:** ebirdyx-ticket-system-demo-pr7-a8fc214
- **Ticket:** TS-7: The store reports an unknown ticket id with an error
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T04:57:55+00:00
- **Model time:** 11.1 s; tokens: 23423 in / 3089 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 1 finding

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

2 file(s) changed, +9 / -3 lines (1 source, 1 test); file types: .py x2.

## Repository context

Code outside the change that the model was shown, found by matching function names (it can match the wrong function).

- `TicketStore.get` (tickets/store.py) is called by 3 other repository function(s) and mentioned in 4 test function(s) (1 added or changed by this change).
- caller of `TicketStore.get`: tickets/service.py:29-33 (`TicketService.get`)
- test of `TicketStore.get`: tests/test_service.py:32-35 (`test_assign_persists`)
- class of `TicketStore.get`: tickets/store.py:25-28 (`TicketStore.__init__`)
- callee of `TicketStore.get`: tickets/store.py:67-72 (`_from_row`)
- caller of `TicketStore.get`: tickets/service.py:35-39 (`TicketService.assign`)
- test of `TicketStore.get`: tests/test_service.py:38-40 (`test_unknown_ticket`)
- caller of `TicketStore.get`: tickets/service.py:41-45 (`TicketService.change_status`)
- test of `TicketStore.get`: tests/test_service.py:43-49 (`test_status_follows_the_workflow`)

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 2 | 0 | 0 |  |
| bandit 1.9.4 | ok | 2 | 0 | 0 | 4 warning(s) in test files were ignored (noise in tests) |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 17.5 s | 5224 / 756 | 0 candidate finding(s) |
| defects | ok | 3.3 s | 4619 / 855 | 1 candidate finding(s) |
| security | ok | 2.6 s | 4553 / 584 | 0 candidate finding(s) |
| standards | ok | 1.4 s | 4626 / 382 | 0 candidate finding(s) |
| verify | ok | 1.8 s | 4401 / 512 | 0 dismissed |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: TicketStore.get raises KeyError for a ticket id that does not exist, instead of returning None.

> TicketStore.get now raises KeyError when the ticket id does not exist.

From code:

```
if row is None:
    raise KeyError(ticket_id)
```

From code:

```
with pytest.raises(KeyError):
    store.get(12345)
```

Where: `tickets/store.py:45`

### 2. MET: TicketStore.get still returns the ticket when it exists.

> TicketStore.get still returns the ticket when it exists.

From code:

```
assert store.get(added.id).title == "Login fails"
```

From code:

```
return _from_row(row)
```

Where: `tests/test_store.py:14`

## Findings

### 1. [HIGH] TicketStore.get now raises KeyError, breaking callers that expect None

- **Category:** logic_defect
- **Location:** `tickets/store.py:42`
- **Location and quotes:** checked against the input
- **Found by:** defects
- **Verification:** supported (TicketStore.get now raises KeyError for missing IDs, but Service.get checks for a None return to raise TicketNotFound, causing a mismatch and likely failing the test that expects TicketNotFound.)

> The updated get method raises KeyError for missing tickets, but callers (e.g., tickets.service.Service.get) check for a None return value to raise their own TicketNotFound exception. This mismatch will cause unhandled KeyError exceptions and failing tests that expect TicketNotFound.

**Evidence**

From code:

```
def get(self, ticket_id: int) -> Ticket:
    """Return the ticket with this id. Raises KeyError if there is none."""
    row = self._db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
    if row is None:
        raise KeyError(ticket_id)
    return _from_row(row)
```

From code:

```
def get(self, ticket_id: int) -> Ticket:
    ticket = self.store.get(ticket_id)
    if ticket is None:
        raise TicketNotFound(ticket_id)
    return ticket
```

## Limitations stated by the model

- The full exception handling and response generation code for the application is not provided, so it cannot be determined whether raising KeyError may lead to information leakage or improper error responses.
