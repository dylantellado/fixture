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

   Expected: 377 messages; acceptance 101, none 96, proposed_times 79, new_request 51,
   reschedule 41, assistant_handoff 9; needs_response 109 true, 268 false.

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
`--annotations`, `--project`, `--location`, `--price-input` / `--price-output`
(US$ per 1M tokens, for models not in `scoring.PRICES`).

Rate limits and transient errors (408, 429, 5xx, network) are retried up to 6
times with exponential backoff. A message that still fails is recorded with its
error, counted under "Failures" in the report and left out of the scores.

## The prompt

- **System part:** short instructions (`prompt.INSTRUCTIONS`) plus the text of
  `docs/data/labeling_rules.md`, read from the file at every run. The "Not adopted"
  (proposals) and "Change log" sections are cut out; if either heading can't be
  found the run stops, so a renamed section can't slip in. The exact text sent is
  saved as `system_prompt.txt` in the run folder.
- **User part:** the mailbox owner, the subject, the earlier messages in the thread
  (oldest first, with From and Date), then the target message (From, To, Date) between
  `=== TARGET MESSAGE ===` markers. Later messages in the thread are never shown.
- **Output:** JSON forced by a response schema (`prompt.RESPONSE_SCHEMA`), temperature 0.

## Outputs

`runs/<UTC timestamp>/` (git-ignored except `report.md`):

| File | Contents |
|---|---|
| `predictions.jsonl` | one line per message: `message_id`, `user_id`, true and predicted label and `needs_response`, `reason`, latency, input/output/thinking tokens, attempts, error |
| `report.md` | run info, label accuracy and per-label precision/recall/F1, confusion matrix, scheduling recall (scheduling email predicted `none` is the worst error), needs_response scores, results by user (user_01–03 vs user_04), tokens, cost and latency, and the 20 most informative mistakes |
| `system_prompt.txt` | the exact system part sent |

Hard-negative accuracy is reported only if the annotations mark hard negatives
(a `hard_negative` field); the v1.2 training annotations don't.

## Files

- `main.py`: command line, runs the calls in parallel, writes the outputs
- `data.py`: loads messages and answers, checks counts, the eval-data guard
- `prompt.py`: rules loading, system and user prompt, response schema
- `gemini.py`: the Vertex AI call, retries, answer checks
- `scoring.py`: metrics and `report.md`
- `test_*.py`: tests for the guard, the prompt builder and the scoring math
