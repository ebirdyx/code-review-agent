# Comparing with a more advanced agent (Claude, ChatGPT, Gemini) through a chat

The course asks for a comparison with a more advanced, costlier agent. A chat subscription is enough: the chat gets exactly the same
text our open model gets, and its answer is validated and scored by the same code (`eval-export`, `eval-import`, `eval-compare`).

## What to compare

| Configuration | What it tells you |
|---|---|
| open model, single pass (`eval-run --pipeline single`) | the model alone, on the same prompt the chat will get |
| open model, our full pipeline (`eval-run`, multi-pass + tools) | what our scaffolding adds to the open model |
| Claude in a chat (`eval-import`) | the advanced agent on the same prompt |
| ChatGPT in a chat (`eval-import`) | a second advanced agent |

Comparing rows 1 and 3 isolates the model. Comparing row 2 with rows 3 and 4 asks the question the project is really about: can an open
model, inside our pipeline, come close to an advanced model used plainly?

## Steps (about an hour for 9 cases and 2 chats)

```powershell
# 0. the open-model side (needs the model key); repeat because answers vary
uv run review-agent eval-run --split dev --repeat 3 --pipeline single --label single-pass
uv run review-agent eval-run --split dev --repeat 3 --label multi-full

# 1. write one paste-ready file per case (the exact text the single-pass pipeline sends)
uv run review-agent eval-export --split dev --out out/chat-prompts
```

2. For each case, open a **new** chat, paste the **whole** content of `out/chat-prompts/<case>.txt`, add nothing, and copy the answer **unedited**
   into `out/answers-claude/<case>.txt`. Note the exact model name and date the chat shows. Repeat in the other product
   (`out/answers-chatgpt/`).
3. Import each set so it is validated and scored like any model's answers:

```powershell
uv run review-agent eval-import out/answers-claude  --split dev --label claude-chat  --model "<exact name and date>" --lenient
uv run review-agent eval-import out/answers-chatgpt --split dev --label chatgpt-chat --model "<exact name and date>" --lenient

# 4. side by side
uv run review-agent eval-compare runs/eval-single-pass-* runs/eval-multi-full-* runs/eval-claude-chat-* runs/eval-chatgpt-chat-* --out evaluation/results/comparison.md
```

`--lenient` removes chatter around the JSON ("Here is my review: ...") before validation. It is counted and printed in the comparison, because
a chat does not enforce the JSON Schema the way our API calls do. Without `--lenient`, such an answer is scored as a failed review.

## Make the numbers trustworthy

- **Label the findings by meaning, not only by location.** Without a labels file the comparison matches a finding to a defect by file and nearby line,
  which is provisional. Use `eval-template` on each folder, correct the labels, write your name in `reviewed_by`, and save the file as `labels.json`
  in the folder (see `evaluation-howto.md`). If you can, label the answers of all configurations together, shuffled, without knowing which model wrote which.
- **Never let a tool or person who has seen the expected answers produce an answer.** The benchmark cases and their answers were written during the
  development of this project: an assistant that helped write them must not be used as the "advanced agent" (the result would be contaminated).
  Use fresh chats, and paste nothing but the exported file.
- **Same text for every model**, one new chat per case, no edits to any answer.

## What to report

| Model | Date | Cases | Valid answers | TP | FP | FN | Precision | Recall | Wrong or invented locations | Answers repaired (`--lenient`) | Cost |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|

`eval-compare` prints most of these. Add what it cannot count: how clear and actionable the explanations are (the usefulness rating 0-2 in the labels
file), whether the quoted evidence is real (the "unconfirmed" column), how long it took, and the cost: chat subscriptions have no per-answer price,
so state the plan used and say that the figure is not comparable with API prices.

## Optional: pull requests

`eval-export --cases-dir <folder of saved pull requests>` works the same way. The chat sees only the diff, the changed files and the ticket, not the
repository context our pipeline adds: say so when you interpret the result.

## Limits to state in the report

- A chat interface can add hidden instructions or tools and is not a controlled API call; it also does not enforce the output schema.
- A few cases, synthetic, one reader for the labels, one run per chat: indicative, not statistical.
- Code pasted into a chat leaves your machine, exactly like code sent to a hosted model: use only the synthetic cases.
