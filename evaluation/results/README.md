# Evaluation results: what each folder is

Every folder here was produced by running the agent for real (model calls, not mocks). **None of the numbers is final**: the
labels of the benchmark were drafted by an AI and never confirmed by a named person, the demonstration scorecards were read by
one person (not blinded), and every comparison is a handful of runs of a non-deterministic model. Each folder says so in its own README.

Expected answers: the benchmark cases are in `../expected/*.json`; the demonstration pull requests are in `../../demo/ticket-system/README.md`
(written before the runs). Hand labels: `../labels/`.

| Folder | Date | What it is | Pipeline, prompt set | Model | Runs |
|---|---|---|---|---|--:|
| `dev-initial/` (+ `dev-initial.md`) | 2026-10-05 | First real model run, 3 benchmark cases | single pass, `review_v1` | gpt-oss:120b | 3 |
| `dev-eval1/` (+ `dev-eval1.md`) | 2026-10-05 | The 9 development cases, 3 repeats each. Scored table in `dev-eval1.md`; labels `../labels/dev-eval1.json` (draft, unconfirmed) | single pass, `review_v1` | gpt-oss:120b | 27 |
| `real-pr-demo/` | 2026-10-12 | First end-to-end review of a real pull request (`ebirdyx/shipping-demo#1`) with its real Jira ticket `KAN-4`: `snapshot/` is the PR, `run/` the review | single pass, `review_v1` | gpt-oss:120b | 1 |
| `ticket-system-demo/` | 2026-10-13 | Six pull requests of `ebirdyx/ticket-system-demo`, four with a planted defect, one clean, one with a vague requirement. Scorecard in its README | multi-pass, `multi_v2` | gpt-oss:120b | 6 |
| `ticket-system-demo-v3/` | 2026-10-14 | The same six pull requests after the first improvements (cross-category merge, consistency check, stricter rules pass) | multi-pass, `multi_v3` | gpt-oss:120b | 6 |
| `context-ablation/` | 2026-10-14 | The six pull requests in three configurations: LLM only, + static tools, + repository context. README has the table; `../scripts/score_context_ablation.py` rebuilds it | multi-pass, `multi_v4` | gpt-oss:120b | 18 |
| `context-dependent/` | 2026-10-14 | Three pull requests whose defect is only visible with the surrounding code, with and without repository context, three runs each | multi-pass, `multi_v4` | gpt-oss:120b | 18 |

## How to read them

- The benchmark folders (`dev-*`) answer "does the agent find planted defects in small synthetic cases?"; they use the original single-pass
  pipeline and say nothing about the multi-pass pipeline.
- The pull-request folders answer "does the whole tool work on realistic pull requests with a real ticket?", and the last two ask what
  repository context adds. They are illustrations, not statistics.
- Folders made before the evaluation harness (`eval-run` writing `eval-config.json`) have no recorded configuration; their settings are in each
  run's `run.json`. From now on, `review-agent eval-run ... --label NAME` records it and `review-agent eval-compare` compares folders
  (see `../../docs/evaluation-howto.md`).
