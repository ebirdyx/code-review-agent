# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Case:** free-shipping-faulty
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** review_v1
- **Date (UTC):** 2026-10-05T00:30:08+00:00
- **Model time:** 2.4 s; tokens: 1871 in / 540 out

## Status: completed, 1 finding

## Coverage

All provided input was included in full.

- No supporting code was provided; only the diff is visible.

## Findings

### 1. [MEDIUM] Free shipping not applied at $100 threshold

- **Category:** boundary_condition
- **Location:** `shop/shipping.py:6`
- **Location and quotes:** checked against the input

> The acceptance criteria state that orders of $100 or more should ship for free, but the implementation only returns free shipping when the total is greater than 100, excluding orders exactly equal to $100.

**Evidence**

From ticket:

```
Orders of $100 or more ship for free.
```

From code:

```
if total > 100:
```

## Limitations stated by the model

- The supporting code defining SHIPPING_FEE and any surrounding context was not provided, so we cannot assess other aspects of the function.
