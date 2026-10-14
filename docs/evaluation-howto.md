# How to evaluate and compare configurations

Every comparison in the report should be reproducible with these commands. Nothing here needs more than the model key
(`OLLAMA_API_KEY` for the free tier, or the key of the profile you choose).

## 1. Run one configuration

```powershell
uv run review-agent eval-run --split dev --repeat 3 --label multi-full
```

`eval-run` saves one run folder per case and repetition, plus `eval-config.json` in the output folder (default
`runs/eval-<label>-<time>`): the exact configuration (pipeline, prompt set, passes, tools, repository context, verifier, model, seed,
agent commit; "+uncommitted" means the code that ran differed from that commit) and an index of every run.

The flags that define a configuration:

| Flag | Meaning |
|---|---|
| `--pipeline single` | one prompt, one model call (the baseline) |
| `--no-tools` | no Ruff / Bandit evidence |
| `--no-context` | no repository context (callers, callees, tests) |
| `--no-verify` | no verifier pass |
| `--passes defects,security` | only some specialist passes |
| `--profile NAME` | another model (see `review-agent profiles`) |
| `--label NAME` | the configuration's name in comparisons (default: made from the flags, e.g. `multi-no-context`) |
| `--cases-dir DIR` | evaluate every example folder (with a `pr.json`) in DIR, e.g. saved pull requests, instead of the split |
| `--repeat N` | runs per case: the model is not deterministic, so repeat |

The held-out split needs `--confirm-frozen`: run it once, after the prompts are frozen.

## 2. The configurations worth comparing

```powershell
uv run review-agent eval-run --split dev --repeat 3 --pipeline single --label single-pass
uv run review-agent eval-run --split dev --repeat 3 --no-tools --no-context --no-verify --label multi-llm-only
uv run review-agent eval-run --split dev --repeat 3 --no-tools --no-context --label multi-verify
uv run review-agent eval-run --split dev --repeat 3 --no-context --label multi-tools
uv run review-agent eval-run --split dev --repeat 3 --label multi-full
```

The benchmark cases are folders without a surrounding repository, so `--no-context` changes nothing on them. To measure repository
context use pull requests (`--cases-dir` with saved pull-request snapshots: `review-agent fetch-pr owner/repo#N`, then copy the
folder from `runs/pr-snapshots/`).

## 3. Compare

```powershell
uv run review-agent eval-compare runs/eval-single-pass-* runs/eval-multi-full-* --out evaluation/results/comparison.md
```

It prints: the configurations (and which settings differ), TP / FP / FN, precision, recall, F1, the range of recall over repeats,
extras and duplicates, exact-line accuracy, mean model time and tokens, a per-case matrix, and **where the labels come from**.

Read the "Recall over repeats" column first: if two configurations differ by less than that spread, you have not shown a difference.

## 4. Labels: provisional until a person confirms them

Without a label file, a finding counts as a defect when it is in the same file near the expected line. That is a rule about
location, not meaning, so it can miss a correct finding reported elsewhere (for example in the caller of a changed function) and
can accept a wrong one. For numbers you intend to report:

```powershell
uv run review-agent eval-template runs/eval-multi-full-<time>     # suggested labels -> evaluation/labels/labels.json
# a person edits each label (tp / fp / duplicate / extra, optional usefulness 0-2) and writes their name in "reviewed_by"
# put the file in the run folder as labels.json (or pass --labels FILE to eval-compare)
```

The rubric is at the top of `src/code_review_agent/evaluation/scoring.py` and was written before any result was seen. A comparison says
"PROVISIONAL" until every configuration has a labels file with a reviewer's name.

## 5. After changing the validator

`review-agent eval-revalidate runs/<folder>` re-checks saved answers without calling the model (use `--cases-dir` if the cases are
not in `evaluation/cases` and `examples`).

## Limits to state in the report

- A few dozen runs on small synthetic cases: indicative, not statistical.
- One model, one reader for the hand labels, results vary from run to run.
- Location matching cannot score defects that live outside the diff; those need hand labels.
