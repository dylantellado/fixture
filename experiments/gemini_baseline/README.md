# Gemini baseline

A one-off experiment: how well does Gemini (on Vertex AI), given only our
labeling rules, label the **training** data? It's a baseline to compare
classifiers against, not the classifier service: no API endpoint, no Docker.

Each of the 377 training messages (user_01 to user_04) gets one call. Gemini
returns a `label` (one of the six), `needs_response` and a one-sentence
`reason`, which are scored against the correct answers.

**Training data only.** eval-v1 is frozen at tag `eval-v1` and must never be run
or used for tuning. Any path under `data/eval/` (including through `..` or a
symlink) or any `user_id` starting with `eval_` exits with an error before
anything is read or sent.

## Setup

1. On `main`, refresh the data (the run checks the counts below and stops if they differ):

   ```sh
   (cd src/ingest && uv run python main.py) && (cd src/preprocess && uv run python main.py)
   ```

   Expected (labeling rules v1.5): 377 messages; acceptance 105, none 92, proposed_times 78,
   new_request 51, reschedule 41, assistant_handoff 10; needs_response 109 true, 268 false.

2. Sign in for Vertex AI with application-default credentials (no API keys, no `.env`):

   ```sh
   gcloud auth application-default login
   ```

   Project `fixture-ac215-96dhbm`, location `global`. The project needs
   `aiplatform.googleapis.com` enabled **and a billing account linked**.

   Model check (2026-10-29): `gemini-3.8-flash` (the default), `gemini-3.7-flash`,
   `gemini-3.5-flash` and `gemini-3-flash-preview` answer on `global`. In
   `us-central1` every Flash model returns 404 for this project, and `gemini-2.5-flash`
   returns 404 everywhere.

## Run

From `experiments/gemini_baseline`:

```sh
uv run python main.py --limit 20          # quick check on the first 20 messages
uv run python main.py                     # all 377
uv run python main.py --model gemini-3.5-flash --concurrency 8
uv run pytest                             # tests, no API calls
```

Flags: `--model` (default in `main.py`), `--limit N` (first N messages in user,
thread, position order), `--concurrency` (default 4), `--users`, `--messages`,
`--annotations`, `--project`, `--location`, `--thinking-budget N` (cap on thinking
tokens per call, default 128; `default` for the model's own thinking), `--price-input` / `--price-output`
(US$ per 1M tokens, for models not in `scoring.PRICES`).

Rate limits and transient errors (408, 429, 5xx, network) are retried up to 6
times with exponential backoff. A message that still fails is recorded with its
error, counted under "Failures" in the report and left out of the scores.

## The prompt

- **System part:** short instructions (`prompt.INSTRUCTIONS`) plus the text of
  `docs/data/labeling_rules.md`, read from the file at every run. The sections in
  `prompt.EXCLUDED_HEADINGS` ("Not adopted" and "Change log") are cut out; if a listed
  heading can't be found the run stops, so a renamed section can't slip in. Tests check
  that no training or eval message id, and no `eval_`, reaches any prompt. Each report
  records the rules version and the sha256 of the exact rules text sent; the full system
  part is saved as `system_prompt.txt` in the run folder.
- **User part:** the mailbox owner, the subject, the earlier messages in the thread
  (oldest first, with From and Date), then the target message (From, To, Date) between
  `=== TARGET MESSAGE ===` markers. Later messages in the thread are never shown.
- **Output:** JSON forced by a response schema (`prompt.RESPONSE_SCHEMA`), temperature 0.

## Outputs

`runs/<UTC timestamp>/` (git-ignored except `report.md`):

| File | Contents |
|---|---|
| `predictions.jsonl` | one line per message: `message_id`, `user_id`, true and predicted label and `needs_response`, `reason`, latency, input/output/thinking tokens, attempts, error |
| `report.md` | run info (model, thinking budget, rules version and sha256 of the rules text sent, git commit), label accuracy and per-label precision/recall/F1, confusion matrix, scheduling recall (scheduling email predicted `none` is the worst error), needs_response scores, results by user (user_01–03 vs user_04), tokens, cost and latency, and the 20 most informative mistakes |
| `system_prompt.txt` | the exact system part sent |

Hard-negative accuracy is reported only if the annotations mark hard negatives
(a `hard_negative` field); the v1.2 training annotations don't.

## Results

Four full runs of the 377 training messages with `gemini-3.8-flash` on `global`,
temperature 0, concurrency 4, 0 failures each. The first three differ only in the rules
text sent and the thinking budget. The fourth uses labeling rules v1.4, which changed both
the rules and 7 training answers, so its column isn't directly comparable with the others.

**The leak:** rules v1.2 had a section 6 listing specific training messages with their
correct answers (label corrections and kept `needs_response` judgment calls), and the
first run sent it to Gemini as part of the rules. Rules v1.3 moved it to
`docs/data/training_conflicts.md`, so the clean runs see only rules in force.

| | Leaked (rules v1.2) | Clean (rules v1.3) | Clean, thinking budget 128 | **Rules v1.4, budget 128 (current defaults)** |
|---|---|---|---|---|
| Run | [`20261029-190428Z`](runs/20261029-190428Z/report.md) | [`20261029-192758Z`](runs/20261029-192758Z/report.md) | [`20261029-194238Z`](runs/20261029-194238Z/report.md) | [`20261030-020451Z`](runs/20261030-020451Z/report.md) |
| Label accuracy | 0.992 (374/377) | 0.984 (371/377) | 0.989 (373/377) | **0.989 (373/377)** |
| Scheduling recall | 0.996 (1 of 281 as `none`) | 0.993 (2 of 281 as `none`) | 0.996 (1 of 281 as `none`) | **1.000 (0 of 285 as `none`)** |
| False alarms (`none` → scheduling) | 0 of 96 | 1 of 96 | 1 of 96 | **0 of 92** |
| needs_response accuracy | 1.000 | 0.997 | 0.992 | **1.000** |
| needs_response precision | 1.000 | 0.991 | 0.973 | **1.000** |
| needs_response recall | 1.000 | 1.000 | 1.000 | **1.000** |
| Thinking tokens (total / median per call) | 124,055 / 189 | 131,129 / 189 | 2,412 / 0 | 3,033 / 0 |
| Estimated cost | $1.55 | $1.42 | $0.95 | $1.12 |
| Latency median / p95 | 3.5 s / 18.4 s | 3.8 s / 20.5 s | 2.4 s / 14.0 s | 2.7 s / 42.4 s |

Costs use $0.75/1M input and $3.75/1M output and thinking (third-party list prices,
no caching discount). The leaked run cost more despite less thinking because section 6
made every prompt longer. The v1.4 run costs more than the third for the same reason: the
new rules add about 580 input tokens per call (1.36M input tokens vs 1.14M). Its p95
latency is server-side: the slowest calls took 60 to 108 s with no thinking, and 7 calls
were retried.

**How much the leak mattered:** only 4 of 377 answers changed between the leaked and
clean runs. Two are tied to section 6: `2b1bc892af42b94d` is listed there, and
`b69c3b5f0b813da8` is in the thread its "TAs splitting course sections" note describes.
The other two (`9d32fed4db2eaa52`, `b596f36dd0aba440`) aren't mentioned in it, so they
are run-to-run variation or a side effect of the changed prompt. A difference of 2 or 3
messages between runs is within that noise.

### Mistakes in the clean run

| message_id | true | predicted | Gemini's reason | Kind |
|---|---|---|---|---|
| `b596f36dd0aba440` | new_request | none | "The message inquires about career center services rather than asking to set up a meeting (D6)…" | **Model error.** "Does the career center do mock technical interviews? I'd really like to practice" asks for a session (D1, E11). |
| `dedb6df0524a507a` | reschedule | none | "This is an announcement of office hours sent to a group mailing list, which is classified as none under E3…" | **Unclear rule:** E3 vs E4/T3 for office hours cancelled one week with a substitute (open question Q1). |
| `b69c3b5f0b813da8` | none | acceptance | "The user confirms and agrees to the proposed section assignment and time (D3)…" | **Unclear rule:** no written rule says that agreeing who teaches which section isn't confirming a meeting time; that judgment was only in the leaked notes. |
| `166482ab09374bcc` | acceptance | assistant_handoff | "The email provides the first notice handing coordination of the visit and schedule to recruiting coordinator Dev Shah (D5, T2) while restating the already agreed date (E14)…" | **Possibly wrong label.** The user had already picked Friday (D3), so "Friday it is!" restates an agreed time (E14) and hands over travel logistics (E1), which the written rules make `none`. Gemini's answer is wrong either way (PR ranks acceptance above handoff). |
| `76885a71c68ac079` | proposed_times | assistant_handoff | "Irene is coordinating on Dr. Achebe's behalf as the initial notice of a handoff (D5, E17, T2, PR3)…" | **Unclear rule:** T2 scope, first handoff in the thread or in the mailbox (open question Q2). |
| `9d32fed4db2eaa52` | proposed_times | assistant_handoff | "Owen is coordinating a meeting on Ruth's behalf as the initial scheduling contact (E17, T2, D5)…" | **Unclear rule:** T2 scope (Q2). |
| `2b1bc892af42b94d` | new_request, needs_response false | new_request, needs_response **true** | "This is an introduction connecting the user with a specialist who will meet with him directly… the user must coordinate to set up a time under NR1." | **Unclear rule:** no needs_response rule covers introductions; the calls for them are only in `training_conflicts.md`. |

1 model error, 5 unclear rules, 1 possibly wrong label. Rules v1.4 then settled the five
unclear rules and the possibly wrong label (E18, T2, E19, NR10, E20), and Gemini got all six
right in the v1.4 run.

### Mistakes in the v1.4 run (current defaults)

| message_id | true | predicted | Gemini's reason | Kind |
|---|---|---|---|---|
| `47af86117df33131` | new_request | assistant_handoff | "Jordan hands off scheduling to Tess under D5/T2…" | **Model error, from missing context:** under the new T2 this isn't the first notice, because Tess was named as scheduler in t019. The prompt shows only the current thread, so Gemini can't know that. |
| `7ae0f9aeb1b22234` | new_request | assistant_handoff | "Tom hands scheduling of the final round over to Gwen, making this an assistant handoff per D5 and PR3…" | **Model error, from missing context:** Gwen was named in t011, outside this thread. |
| `49ec03bc60f62177` | new_request | assistant_handoff | "Jordan hands off scheduling the final round interviews to Tess (D5, T2)…" | **Model error, from missing context:** Tess was named in t020, outside this thread. |
| `e3f8c97e38dafbee` | proposed_times | reschedule | "The target message cancels/reschedules an existing recurring meeting occurrence to October 26 at 10:00 as a directive move under D4 and NR9." | **Unclear rule:** Marcus already moved the meeting ("would it be ok to skip our mon 10/19 meeting?"), so Prof. Osei's "Mondays only, so October 26 at 10:00" is a reply inside the move (T1: `proposed_times`). The new E18 ("cancelling one occurrence and offering a new time → `reschedule`") doesn't say it covers only the message that makes the move. Both runs on v1.3 rules got this right. |

3 model errors (all from the new T2 needing mailbox history the prompt doesn't include), 1
unclear rule, 0 possibly wrong labels. Gemini can't get the three T2 cases right unless the
prompt says who the user already schedules through, e.g. by listing earlier handoffs in the
mailbox.

### Thinking budget

The third run sets `--thinking-budget 128`. I picked it from the leaked run's thinking per
call (25th percentile 136 tokens, median 189; the clean run's are 135 and 189): it sits below
the 25th percentile, so it binds on most calls, and it caps the long tail (in the clean run,
17 calls over 1,000 tokens produced 36% of all thinking). In practice the model
treated 128 as "almost no thinking": the median was 0 and the total 2,412 tokens. Even so,
label accuracy and scheduling recall held (0.989 and 0.996, within run-to-run noise of the
clean run), cost fell 33% and median latency 37%. The cost was 3 extra `needs_response`
= true on introductions (`6036baac6f4ce32a`, `9d817cdfb67a8e11`, `2b1bc892af42b94d`): the
same rule gap as above, in the safer direction (an unneeded reply, never a missed one).

**Decision (v1.4): the default is now `--thinking-budget 128`** (`DEFAULT_THINKING_BUDGET` in
`main.py`). It gave the same label quality at a third less cost and latency, and its
needs_response gap on introductions is closed by NR10: the v1.4 run scores 1.000 on
needs_response. Use `--thinking-budget default` for the model's own thinking. These are
training numbers near the ceiling, so a thinking setting that matters on harder mail may not
show up here.

## Files

- `main.py`: command line, runs the calls in parallel, writes the outputs
- `data.py`: loads messages and answers, checks counts, the eval-data guard
- `prompt.py`: rules loading, system and user prompt, response schema
- `gemini.py`: the Vertex AI call, retries, answer checks
- `scoring.py`: metrics and `report.md`
- `test_*.py`: tests for the guard, the prompt builder and the scoring math
