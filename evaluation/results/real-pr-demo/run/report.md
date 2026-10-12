# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Revision reviewed:** ebirdyx/shipping-demo#1, head `a29a74ec5dc319f7aac216c2a4aec231b231e5e9`, base `74fa2097d5d539cff7ae515fc0251a63c216fd7a` (https://github.com/ebirdyx/shipping-demo/pull/1)
- **Case:** ebirdyx-shipping-demo-pr1-a29a74e
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** review_v1
- **Date (UTC):** 2026-10-12T20:02:29+00:00
- **Model time:** 1.6 s; tokens: 1937 in / 436 out

## Status: completed, 1 finding

## Coverage

All provided input was included in full.

- No missing inputs.

## Findings

### 1. [MEDIUM] Free shipping not applied to orders exactly $100

- **Category:** boundary_condition
- **Location:** `shop/shipping.py:6`
- **Location and quotes:** checked against the input

> The ticket requires orders of $100 or more to ship for free, but the implementation only returns free shipping when total is greater than 100, excluding orders that are exactly $100.

**Evidence**

From ticket:

```
Orders of $100 or more ship for free.
```

From code:

```
if total > 100:
```
