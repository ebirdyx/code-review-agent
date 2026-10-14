# Does the "cannot determine" guidance cause wrong verdicts?

Date: 2026-10-14. Question: prompt sets `multi_v3` and `multi_v4` tell the compliance pass to answer "cannot determine" when a criterion leaves something
undefined. In one run of the full pipeline on `load-config` the compliance pass wrote an explanation describing the violated requirement exactly, yet gave the
verdict "cannot determine". Does the guidance cause such wrong verdicts?

Method: only the compliance pass (one model call per run, no tools, no verifier, no repository context), the nine development cases, 3 repeats, `gpt-oss:120b`
on the free tier, under three prompt sets that differ only in that guidance: `multi_v2` (none), `multi_v3` (added), `multi_v4` (current). Raw verdicts of every run:
`verdicts.json`. Then 8 more runs of `load-config` with `multi_v4`, with and without the static-analysis block in the prompt.

How each case is scored (the tickets were read first): in `free-shipping-faulty`, `password-min-length`, `marketing-opt-in`, `discounted-total` and `load-config`
criterion 1 is violated, so the right verdict is NOT MET; in `free-shipping-fixed` and `slugify-title` every criterion is met; in `free-shipping-ambiguous` both
criteria are undefined ("large orders", "small orders"), so "cannot determine" is the honest verdict. `user-search-sql` (a security defect not tied to its single criterion) is left out.

## Results

| Prompt set | Violated criterion 1 (15 runs): NOT MET / MET / cannot determine | Correct changes (6 runs): runs with a verdict other than MET | Vague case (6 verdicts): cannot determine / MET / NOT MET |
|---|--:|--:|--:|
| `multi_v2` (no guidance) | 15 / 0 / 0 | 0 | 0 / 6 / 0 |
| `multi_v3` (guidance added) | 15 / 0 / 0 | 0 | 4 / 2 / 0 |
| `multi_v4` (current) | 15 / 0 / 0 | 0 | 4 / 2 / 0 |

`load-config` alone, `multi_v4`, criterion 1: **8 of 8 NOT MET with the static-analysis block in the prompt, 8 of 8 without it.**

## What it shows

- **No evidence that the guidance causes wrong verdicts on clear criteria:** 15 of 15 violated criteria were marked NOT MET under every prompt set, and the correct
  changes were marked MET every time.
- **The guidance does what it was added for:** on the vague case, "cannot determine" went from 0 of 6 verdicts to 4 of 6. (The other 2 of 6 still say MET: it is not reliable.)
- **The single wrong verdict in the full pipeline is not reproduced:** `load-config` under `multi_v4` gave NOT MET in 19 of 19 compliance-only runs (3 + 8 + 8), so that run looks like
  ordinary run-to-run randomness of the model, about 1 run in 22 for this case. The compliance call of the full pipeline sees the same input as these runs.
  Sampling noise can hide an effect of a few percent: this experiment would not detect one.

## Limits

One model, one benchmark of nine small cases, three repeats per case, scored by one reader against an answer key I read from the tickets (not blinded).
"Wrong verdict on a clear criterion" was rare (about 4%) even where it happened, so a larger sample would be needed to say more than "not observed here".
