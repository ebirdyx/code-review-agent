# Team coding rules (example)

Put a file like this at `.review-agent/rules.md` on your base branch, or pass it with `--rules`.
Short, checkable rules work best. Each bullet is one rule.

- Never build SQL by joining or formatting strings; always use parameterised queries.
- Never use `print()` for diagnostics; use the `logging` module.
- Every public function has a docstring that says what it returns.
- No secrets, tokens or passwords in source code.
- Catch specific exceptions; never use a bare `except:` or `except Exception:` that swallows the error silently.
