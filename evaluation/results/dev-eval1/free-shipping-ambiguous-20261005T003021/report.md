# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Case:** free-shipping-ambiguous
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** review_v1
- **Date (UTC):** 2026-10-05T00:30:21+00:00
- **Model time:** 2.2 s; tokens: 1863 in / 580 out

## Status: completed, 1 finding

## Coverage

All provided input was included in full.

- No supporting code was provided; only the diff is visible.

## Findings

### 1. [LOW] Hard‑coded shipping threshold

- **Category:** maintainability
- **Location:** `shop/shipping.py:6`
- **Location and quotes:** checked against the input

> The shipping cost function uses a literal value `100` to decide when shipping is free. Hard‑coding the threshold makes the rule difficult to change and obscures its meaning; it should be defined as a named constant or configuration value.

**Evidence**

From code:

```
if total > 100:
```

## Limitations stated by the model

- The ticket does not specify the exact monetary threshold for free shipping, so it is unclear whether using `> 100` matches the intended requirement (e.g., whether the threshold should be inclusive).
- The supporting code defining `SHIPPING_FEE` and any related constants is missing, preventing verification of type consistency and default fee handling.
