# Model comparison notes (working notes for the report and the slides)

These are observations from single real runs, **not a benchmark**. One pull request, one run per model, so differences
can be luck (the two Qwen2.5 runs below, same input, gave the same verdicts, which is mildly reassuring, but it is still
n = 1 PR). Use them as illustrations ("what we saw") and say so. The measured comparison (dev set, labelled findings,
precision/recall) is still to be done.

## About "free" (course requirement: free agents)

- The working default, `gpt-oss:120b`, runs on **Ollama Cloud's free tier** (usage-limited). It is open-weight (Apache-2.0)
  and can also run locally with Ollama, so it satisfies "free and open" but it is **not** the model named in the team plan.
- The Qwen runs below used **OpenRouter, a hosted service that charges per token** (about $0.006 and $0.001 per run on this
  small PR). The weights are open (Apache-2.0) and the same model can run for free locally with Ollama
  (`qwen2.5-coder:7b` fits an 8 GB GPU), but **we did not run the local one yet**. Say it plainly in the report: the
  Qwen results were obtained with a small fee; the free options are gpt-oss on the free tier, or Qwen locally.
- The point of the comparison: the same pipeline gives results with a free model and with the (cheap) hosted Qwen, and
  the numbers below show how they differ.

## Privacy: provider versus local (state this in the report)

Every review sends the pull request text (diff, changed source files, ticket, rules) to the model. Where that goes
depends on the profile:

| Profile type | Where the code goes | Consequence |
|---|---|---|
| Local Ollama (`qwen25-coder-*-local`) | stays on the machine | no third party sees the code; slower, needs a GPU or RAM, weaker models |
| Ollama Cloud (`gpt-oss-*-cloud`) | sent to Ollama's servers | a third party receives the code; free tier has usage limits; terms can change |
| OpenRouter (`*-openrouter`) | sent to OpenRouter **and** to the provider it routes to | two third parties; the routed provider can change between calls; check the data and retention policy before use |

Rules we follow: only synthetic benchmark cases and our own demo repositories were sent to hosted models; do not use a
hosted profile on confidential or employer/client code (use a local model, or a provider whose terms you have read).
API keys live in user-level environment variables and in CI secrets, never in the repository.
The tool itself only reads from GitHub and Jira (the one write is the optional PR comment, which needs an explicit flag).
Even with a local model, the PR comment and the Actions artifact live on GitHub, so they are only as private as the repository.

## Language coverage (state this in the report)

- Static analysis (Ruff, Bandit) is **Python only**. For other languages those tools are skipped and the report says
  so; the model-based passes still run on the diff.
- The benchmark (22 cases) and all measured results are **Python only**. We have not measured the quality of reviews of
  TypeScript, Java or other languages, so do not claim it works equally well there.
- Adding a language means adding a tool to `context/evidence.py` (for example ESLint for TypeScript) and benchmark cases in that language.

## Setup common to all runs

- Pull request: `ebirdyx/shipping-demo#1`, 1 file, +2 lines. Ticket **KAN-4** (real Jira), 2 acceptance criteria.
- Known defect (planted): `shop/shipping.py:6` uses `total > 100` where the ticket says "$100 or more" (should be `>=`).
- Same pipeline (`multi_v2`: compliance, defects, security, verifier; the standards pass was skipped, no team rules).
  Static analysis (Ruff, Bandit): 0 warnings. Date: 2026-10-13.
- Correct checklist: criterion 1 ("$100 or more ships free") = **NOT MET**; criterion 2 ("under $100 pays the fee") = MET.

## Side by side

| | gpt-oss:120b (Ollama Cloud) | qwen2.5-coder 32B (OpenRouter) | qwen3-coder 30B-A3B (OpenRouter) |
|---|---|---|---|
| Role | working default, not the professor's model | Qwen family named by the professor | newer Qwen coder, 3.3B active parameters |
| Found the planted bug | yes | yes | yes |
| Found by which passes | compliance + defects | compliance + defects | defects only (compliance found nothing) |
| Severity given | HIGH | MEDIUM | HIGH |
| Checklist criterion 1 (correct: NOT MET) | NOT MET (correct) | MET (**wrong**) | MET (**wrong**) |
| Checklist criterion 2 (correct: MET) | MET (correct) | NOT MET (**wrong**) | MET (correct) |
| Checklist consistent with its own finding | yes | **no** | **no** |
| Evidence attached to the finding | code + ticket line, relevant | code, plus a ticket quote about the *other* criterion | code + the right ticket line |
| Verifier | "supported" | first run: pass lost (see below); re-run after the fix: "supported" | "supported" |
| JSON hygiene | clean | Markdown fences in every pass; once a field name without quotes | clean, no format notes |
| Tokens (in / out, whole review) | 9266 / 2213 | 9158 / 506 | 9130 / 528 |
| Model time (sum of passes) | 14.1 s | about 20 s | about 25 s |
| Approximate cost (catalogue prices) | free tier | about $0.006 | about $0.001 |

Cost is computed from the token counts and the OpenRouter prices; it grows with the size of the pull request.

## What to say about it

1. **All three found the defect; they differ in reliability.** The reliable part is the defects pass: every model found
   the boundary error there. The checklist is where the Qwen models went wrong, so a reader who only looked at the
   checklist would be misled.
2. **"Grounded is not true."** Every quote in the Qwen checklists exists in the input and every file and line is real, yet
   verdicts are wrong. Our checks prove that cited text exists, not that the conclusion is right. This is why the human
   reviewer keeps the final decision and every report carries a disclaimer.
3. **Specialist passes give redundancy.** With qwen3-coder the compliance pass missed the defect and the defects pass
   caught it. A single prompt would have had one chance; the multi-pass design had two.
4. **The verifier did not catch the contradictions.** It said "supported" for the finding in each run, which is correct for
   the finding, but nobody checks the checklist against the findings. Two of three models contradict themselves.
5. **Guard rails are visible, not silent.** A failed verifier pass is reported as "findings NOT double-checked" with partial
   coverage; format problems (fences, unquoted names) are listed as notes.
6. **A real bug found by testing with a real model.** The first Qwen2.5 run lost its verifier pass because the model wrote
   `verdict:` without quotes. The parser now quotes a bare field name that starts a line (so it cannot touch text inside a
   string) and shows a warning; anything else broken still fails. Our mocked tests had never produced that format, which is
   an argument for testing with real models.
7. **Switchable by design.** Changing model is one flag (`--profile NAME`); pipeline, validation and report are identical.
   That is how the professor's model family can be used without rewriting anything.
8. **Smaller is not necessarily worse here, but this is one example.** The 3.3B-active-parameter model matched or beat the
   32B model on this PR (right severity, relevant evidence, no format noise) at a sixth of the cost. Do not generalise from
   one PR.

## Idea this suggests (not built yet)

A consistency check: flag a criterion marked MET when the same file and line carries a finding, or NOT MET with no finding.
It would have caught the contradiction in both Qwen runs automatically. Also: show the checklist as "needs a human look"
when it disagrees with the findings.

## To fill in as we go

- [x] Qwen2.5-Coder 32B re-run after the verifier fix (verifier usable).
- [x] `qwen3-coder-30b-openrouter` on the same PR.
- [ ] Same comparison on the dev set (numbers: precision, recall, hallucinated locations, invalid outputs).
- [ ] Local Qwen via Ollama (qwen2.5-coder 7B/14B) if a teammate's machine can run it.
- [ ] Claude and Gemini, for the comparison required by the course (postponed by the team).
