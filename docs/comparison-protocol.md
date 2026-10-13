# Comparing with Claude / ChatGPT / Gemini without an API key

The course asks for a comparison with a costlier agent. A chat subscription is enough: the web chat gets exactly the
same text our open model gets, and its answer goes through exactly the same validation and scoring.

**Rules that keep the comparison fair**

- Same cases, same prompt version, same labelling grid, same validation for every model.
- Use the **single-pass** prompt (`review_v1`, which is what `build-context` and `validate` use): one message in, one
  JSON answer out. Run the open models with `--pipeline single --prompt-version review_v1` so everyone gets the same text.
  (The multi-pass pipeline makes several calls; compare it model-to-model with the API profiles, not through a chat.)
- One fresh conversation per case (no memory of earlier cases), the same instruction each time, note the model name
  and the date shown by the chat.
- Never edit the model's answer by hand. Paste it as is.
- Do not paste confidential code into a chat tool. The benchmark cases are synthetic and safe to paste.

## Steps for one case

1. Build the exact text the open model would receive:

   ```powershell
   uv run review-agent build-context evaluation/cases/<case> --out out/<case>.txt
   ```

   (For a real pull request, `fetch-pr` first, then `build-context` on the folder it created in `runs/pr-snapshots/`.)

2. Open a **new** chat. Paste the whole file (it has a SYSTEM MESSAGE part and a USER MESSAGE part; paste both, one
   after the other, in one message). Add nothing else except: *"Answer with the JSON object only."* Send it.

3. Copy the answer as is into `out/<case>.<model>.txt` (for example `out/safe-divide.claude-opus.txt`).

4. Validate and report it, with no model call:

   ```powershell
   uv run review-agent validate evaluation/cases/<case> out/<case>.<model>.txt
   ```

   This checks JSON, schema, files, lines and quotes exactly as for the open model, and writes a run folder in `runs/`.

5. Score runs the same way as the open models (`eval-template`, fill in the labels, `eval-score`), using the same
   labelling grid, ideally by someone who does not know which model wrote which answer.

## What to record (one row per model)

| Model | Date | Cases | Valid JSON | TP | FP | FN | Precision | Recall | Wrong line / invented quotes | Cost | Notes |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|---|---|

Cost: chat subscriptions have no per-answer cost; state the plan used and say the figure is not comparable with API prices.
Compare also: how often the answer needed unwrapping (format notes), how many quotes did not exist in the input, and the
model's stated limitations.

## Honest limits to state in the report

- A chat interface can add hidden instructions and tools; it is not a controlled API call.
- Small, synthetic cases: the numbers are indicative, not statistics.
- The human labelling grid is the same for all models, but the labeller's judgement is still human.
