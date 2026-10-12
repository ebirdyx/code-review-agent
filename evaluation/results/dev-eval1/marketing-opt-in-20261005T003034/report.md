# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Case:** marketing-opt-in
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** review_v1
- **Date (UTC):** 2026-10-05T00:30:34+00:00
- **Model time:** 1.7 s; tokens: 1917 in / 515 out

## Status: completed, 1 finding

## Coverage

All provided input was included in full.

- No missing inputs.

## Findings

### 1. [HIGH] Missing opt-in check for marketing recipients

- **Category:** requirement_mismatch
- **Location:** `marketing/campaigns.py:6`
- **Location and quotes:** checked against the input

> The function `marketing_recipients` includes users based only on `not u.unsubscribed` and does not verify that users have explicitly opted in to marketing, violating acceptance criterion 1 which requires only opted‑in users to receive the newsletter.

**Evidence**

From ticket:

```
1. Only users who explicitly opted in to marketing receive the newsletter.
```

From code:

```
return [u.email for u in users if not u.unsubscribed]
```

From code:

```
def marketing_recipients(users: list[User]) -> list[str]:
```

From code:

```
class User:
    email: str
    opted_in_to_marketing: bool = False
    unsubscribed: bool = False
```
