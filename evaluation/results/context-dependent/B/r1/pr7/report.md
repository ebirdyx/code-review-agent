# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/ticket-system-demo#7, head `a8fc214d01f07394b509d16ef58e2fcdf89d19b2`, base `31011419c5a58b58220c9be837409de5616c9a2f` (https://github.com/ebirdyx/ticket-system-demo/pull/7)
- **Case:** ebirdyx-ticket-system-demo-pr7-a8fc214
- **Ticket:** TS-7: The store reports an unknown ticket id with an error
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** multi_v4
- **Date (UTC):** 2026-10-14T04:52:39+00:00
- **Model time:** 6.5 s; tokens: 15734 in / 2131 out
- **Pipeline:** multi-pass (compliance, defects, security, standards, verify)

## Status: completed, 0 findings

## Coverage

All provided input was included in full.

- No missing inputs.

## Change profile

2 file(s) changed, +9 / -3 lines (1 source, 1 test); file types: .py x2.

## Automated checks (static analysis)

Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; warnings on untouched lines are counted but not blamed on this change.

| Tool | Status | Files | Warnings | On changed lines | Note |
|---|---|--:|--:|--:|---|
| ruff 0.17.0 | ok | 2 | 0 | 0 |  |
| bandit 1.9.4 | ok | 2 | 0 | 0 | 4 warning(s) in test files were ignored (noise in tests) |

## Specialist passes

| Pass | Status | Model time | Tokens | Result |
|---|---|--:|--:|---|
| compliance | ok | 2.2 s | 4402 / 884 | 0 candidate finding(s) |
| defects | ok | 2.1 s | 3797 / 522 | 0 candidate finding(s) |
| security | ok | 1.6 s | 3731 / 374 | 0 candidate finding(s) |
| standards | ok | 1.1 s | 3804 / 351 | 0 candidate finding(s) |
| verify | skipped | n/a | n/a | no model-reported candidate findings to verify |

## Requirements checklist

Each acceptance criterion of the ticket, with the model's verdict. "Cannot determine" means the provided content did not allow a judgement.

### 1. MET: TicketStore.get raises KeyError for a ticket id that does not exist, instead of returning None.

> TicketStore.get now raises a KeyError when the ticket id does not exist, as required.

From code:

```
if row is None:
    raise KeyError(ticket_id)
```

From pr_description:

```
The store reports an unknown ticket id with a KeyError instead of returning None.
```

From code:

```
with pytest.raises(KeyError):
    store.get(12345)
```

### 2. MET: TicketStore.get still returns the ticket when it exists.

> TicketStore.get returns the ticket object when the id exists, satisfying the second criterion.

From code:

```
def get(self, ticket_id: int) -> Ticket:
```

From code:

```
return _from_row(row)
```

From code:

```
assert store.get(added.id).title == "Login fails"
```

## Findings

No findings were reported. This is the model's claim, not a guarantee that the change is correct.

## Limitations stated by the model

- The review only has access to the changed files and supporting code provided. It cannot determine whether other parts of the codebase rely on TicketStore.get returning None for missing tickets, which could cause runtime errors after this change.
