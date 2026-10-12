# Evaluation results: dev

> **PROVISIONAL.** The labels have not been confirmed by a named human reviewer (draft by: AI assistant (draft; a team member must confirm and set reviewed_by)). Do not report these numbers as final.

- Model(s): gpt-oss:120b @ https://ollama.com
- Prompt version(s): review_v1
- Runs scored: 27 (0 failed)

## Per run

| Run | Group | TP | FP | FN | Extra | Dup | Unconfirmed | Model time |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| discounted-total | logic | 1 | 0 | 0 | 0 | 0 | 0 | 1.7 s |
| discounted-total | logic | 1 | 0 | 0 | 0 | 0 | 0 | 1.8 s |
| discounted-total | logic | 1 | 0 | 0 | 0 | 0 | 0 | 1.5 s |
| free-shipping-ambiguous | ambiguous | 0 | 1 | 0 | 1 | 0 | 0 | 2.6 s |
| free-shipping-ambiguous | ambiguous | 0 | 0 | 0 | 0 | 0 | 0 | 2.0 s |
| free-shipping-ambiguous | ambiguous | 0 | 0 | 0 | 1 | 0 | 0 | 2.2 s |
| free-shipping-faulty | boundary | 1 | 0 | 0 | 0 | 0 | 0 | 2.3 s |
| free-shipping-faulty | boundary | 1 | 0 | 0 | 0 | 0 | 0 | 2.4 s |
| free-shipping-faulty | boundary | 1 | 0 | 0 | 0 | 0 | 0 | 2.4 s |
| free-shipping-fixed | correct | 0 | 0 | 0 | 0 | 0 | 0 | 1.3 s |
| free-shipping-fixed | correct | 0 | 0 | 0 | 0 | 0 | 0 | 2.4 s |
| free-shipping-fixed | correct | 0 | 0 | 0 | 0 | 0 | 0 | 1.3 s |
| load-config | error_handling | 1 | 0 | 0 | 0 | 0 | 0 | 2.0 s |
| load-config | error_handling | 1 | 0 | 0 | 0 | 0 | 0 | 2.6 s |
| load-config | error_handling | 1 | 0 | 0 | 0 | 0 | 0 | 3.6 s |
| marketing-opt-in | requirement | 1 | 0 | 0 | 0 | 0 | 0 | 1.7 s |
| marketing-opt-in | requirement | 1 | 0 | 0 | 0 | 0 | 0 | 1.3 s |
| marketing-opt-in | requirement | 1 | 0 | 0 | 0 | 0 | 0 | 1.4 s |
| password-min-length | boundary | 1 | 0 | 0 | 0 | 0 | 0 | 1.3 s |
| password-min-length | boundary | 1 | 0 | 0 | 0 | 0 | 0 | 1.8 s |
| password-min-length | boundary | 1 | 0 | 0 | 0 | 0 | 0 | 1.8 s |
| slugify-title | correct | 0 | 0 | 0 | 0 | 0 | 0 | 2.9 s |
| slugify-title | correct | 0 | 0 | 0 | 0 | 0 | 0 | 1.9 s |
| slugify-title | correct | 0 | 0 | 0 | 0 | 0 | 0 | 1.8 s |
| user-search-sql | security | 1 | 0 | 0 | 0 | 0 | 0 | 1.8 s |
| user-search-sql | security | 1 | 0 | 0 | 0 | 0 | 0 | 2.2 s |
| user-search-sql | security | 1 | 0 | 0 | 0 | 0 | 0 | 1.6 s |

## Overall

- True positives: 18, false positives: 1, false negatives: 0
- Precision: 0.95   Recall: 1.00   F1: 0.97
- Plausible extras (not in precision): 2; duplicate reports merged: 0
- Location accuracy on true positives: exact 14/18 (78%), within 2 lines 18/18 (100%)
- Category matches expected on true positives: 12/18 (67%)
- Usefulness (0-2), mean over 21 rated finding(s): 1.81
- Mean model time: 2.0 s; mean wall-clock: 2.1 s
- Tokens: 50955 in / 12887 out
- Inference cost: not measured (Ollama Cloud returns no per-request cost).

## By group

| Group | Runs | TP | FP | FN | Recall |
|---|--:|--:|--:|--:|--:|
| ambiguous | 3 | 0 | 1 | 0 | n/a |
| boundary | 6 | 6 | 0 | 0 | 1.00 |
| correct | 6 | 0 | 0 | 0 | n/a |
| error_handling | 3 | 3 | 0 | 0 | 1.00 |
| logic | 3 | 3 | 0 | 0 | 1.00 |
| requirement | 3 | 3 | 0 | 0 | 1.00 |
| security | 3 | 3 | 0 | 0 | 1.00 |

_Sample size: 9 cases, 27 runs. With so few cases, a difference of one finding moves these numbers a lot: treat them as indicative, not statistically established._
