# Evaluation results: dev

> **PROVISIONAL.** The labels have not been confirmed by a named human reviewer (draft by: AI assistant (draft; a team member must confirm and set reviewed_by)). Do not report these numbers as final.

- Model(s): gpt-oss:120b @ https://ollama.com
- Prompt version(s): review_v1
- Runs scored: 3 (0 failed)

## Per run

| Run | Group | TP | FP | FN | Extra | Dup | Unconfirmed | Model time |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| free-shipping-ambiguous | ambiguous | 0 | 1 | 0 | 1 | 0 | 0 | 5.0 s |
| free-shipping-faulty | boundary | 1 | 0 | 0 | 0 | 0 | 0 | 1.6 s |
| free-shipping-fixed | correct | 0 | 0 | 0 | 0 | 0 | 0 | 4.3 s |

## Overall

- True positives: 1, false positives: 1, false negatives: 0
- Precision: 0.50   Recall: 1.00   F1: 0.67
- Plausible extras (not in precision): 1; duplicate reports merged: 0
- Location accuracy on true positives: exact 1/1 (100%), within 2 lines 1/1 (100%)
- Category matches expected on true positives: 0/1 (0%)
- Usefulness (0-2), mean over 3 rated finding(s): 1.00
- Mean model time: 3.6 s; mean wall-clock: 3.8 s
- Tokens: 5599 in / 1772 out
- Inference cost: not measured (Ollama Cloud returns no per-request cost).

## By group

| Group | Runs | TP | FP | FN | Recall |
|---|--:|--:|--:|--:|--:|
| ambiguous | 1 | 0 | 1 | 0 | n/a |
| boundary | 1 | 1 | 0 | 0 | 1.00 |
| correct | 1 | 0 | 0 | 0 | n/a |

_Sample size: 3 cases, 3 runs. With so few cases, a difference of one finding moves these numbers a lot: treat them as indicative, not statistically established._
