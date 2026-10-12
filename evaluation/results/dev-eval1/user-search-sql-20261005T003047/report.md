# Code review report

> Automated review by a language model. It can be wrong or miss problems. "Checked" below means only that cited files, lines and quotes exist in the input; it does not mean a finding is correct. The human reviewer makes the final decision.

- **Case:** user-search-sql
- **Model:** gpt-oss:120b at https://ollama.com
- **Prompt version:** review_v1
- **Date (UTC):** 2026-10-05T00:30:47+00:00
- **Model time:** 1.8 s; tokens: 1898 in / 400 out

## Status: completed, 1 finding

## Coverage

All provided input was included in full.

- No supporting code was provided; only the diff is visible.

## Findings

### 1. [HIGH] SQL injection vulnerability in find_users_by_name

- **Category:** security
- **Location:** `users/search.py:8`
- **Location and quotes:** checked against the input

> The function builds the SQL query by directly interpolating the user-provided 'name' parameter into the query string, allowing an attacker to inject arbitrary SQL code. This violates secure coding practices and could lead to data leakage or modification.

**Evidence**

From code:

```
query = f"SELECT id, name, email FROM users WHERE name = '{name}'"
```

## Limitations stated by the model

- No supporting code was provided, so the review cannot assess how find_users_by_name is integrated, whether inputs are validated elsewhere, or if the function is used in a context that mitigates injection risks.
