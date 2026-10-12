# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Case:** discounted-total
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** review_v1
- **Date (UTC):** 2026-10-05T00:30:32+00:00
- **Model time:** 1.5 s; tokens: 1901 in / 480 out

## Status: completed, 1 finding

## Coverage

All provided input was included in full.

- No supporting code was provided; only the diff is visible.

## Findings

### 1. [HIGH] Discount calculation is incorrect

- **Category:** logic_defect
- **Location:** `shop/pricing.py:11`
- **Location and quotes:** checked against the input

> The function returns `subtotal * discount_percent / 100`, which computes the discount amount rather than the final total after discount. According to the acceptance criteria, a 20% discount on a cart worth 200 should result in 160, but the current implementation would return 40. A 0% discount should leave the total unchanged, but the function would return 0.

**Evidence**

From code:

```
return subtotal * discount_percent / 100
```

From ticket:

```
A 20% discount on a cart worth 200 gives a total of 160.
```

From ticket:

```
A 0% discount leaves the total unchanged.
```
