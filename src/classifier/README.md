# classifier

Labels one email with Gemini (Vertex AI), following
[`docs/data/labeling_rules.md`](../../docs/data/labeling_rules.md): one of the six labels
plus `needs_response`, with a one-line reason. The web app uses it to label the signed-in
user's recent Gmail emails. It only reads what it's sent: it never touches Gmail or Calendar.

**Privacy:** email text is sent to Gemini in our own GCP project (`fixture-ac215-96dhbm`).
This service never logs or saves email text, subjects or senders. Logs hold message ids,
labels, timing and token counts only.

## Files

| File | What it does |
|------|--------------|
| `main.py` | FastAPI app: `GET /health`, `POST /classify`, request checks, logging. |
| `prompt.py` | Builds the prompt (no network). Same function names as `experiments/gemini_baseline/prompt.py`, for comparison; nothing is imported from `experiments/`. |
| `gemini.py` | Calls Gemini with structured JSON output, temperature 0; retries rate limits with backoff; checks the answer. |
| `test_prompt.py`, `test_main.py` | Tests, with fake threads. Gemini is never called. |

## Settings

| Variable | Default | |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | none (required to classify) | `fixture-ac215-96dhbm` |
| `GOOGLE_CLOUD_LOCATION` | `global` | Gemini 3.x Flash models are served on the global endpoint for our project; `us-central1` returned 404 (2026-10-29). |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Checked with a test call on 2026-10-29. |
| `GEMINI_THINKING_BUDGET` | `128` | Max thinking tokens per email. The baseline showed the same accuracy as the model's default for about a third less cost and latency. |
| `RULES_PATH` | `docs/data/labeling_rules.md` | Docker mounts the repo's file read-only. |

Credentials are Google application-default credentials: run
`gcloud auth application-default login` once. No API keys, no `.env`, no `secrets/`.

## The prompt

- **System instruction:** short instructions, then the labeling rules file read at startup,
  without the sections that must never reach the model: "Not adopted" (proposals),
  "Training data" (training answers by message id) and "Change log" (`EXCLUDED_SECTIONS` in
  `prompt.py`, matched by heading). The rules version (e.g. `1.2`) is read from the file's
  `**Version X.Y` line and returned with every label. The service won't start if the file
  is missing, has no version, or doesn't have exactly one heading for each excluded section:
  when the rules file is reorganized (rules v1.3 moves "Training data" to
  `docs/data/training_conflicts.md`), update `EXCLUDED_SECTIONS` on purpose. A test checks
  that no training message id reaches the prompt.
- **User message:** the earlier thread messages oldest-first (the 10 most recent before the
  target), then the target email. Each is in its own `<earlier_message>` / `<target_email>`
  block; bodies over 4,000 characters are cut. Messages after the target are never sent.
- **Untrusted text:** the model is told that everything inside the blocks is email data and
  to ignore instructions in it (rule E12). Email text that tries to open or close a block
  (e.g. a fake `</target_email>`) is neutralized.
- **Output:** JSON with `reason`, `label` (an enum of the six labels) and `needs_response`.
  Temperature 0, thinking budget `GEMINI_THINKING_BUDGET`. The answer is checked again in code.
- **NR1 in code:** a message marked `from_user` always gets `needs_response: false`,
  whatever the model says.

## Endpoints

### `GET /health`

Doesn't call Gemini. The web app reads `rules_version` from here to decide which cached
labels are out of date.

```json
{"status": "ok", "model": "gemini-3.8-flash", "rules_version": "1.2"}
```

### `POST /classify`

```json
{
  "thread": [
    {"from": "Jordan Lee <jordan@example.com>", "date": "Tue, 13 Oct 2026 09:12:00 -0400",
     "subject": "Coffee chat?", "body": "Could we find 20 minutes next week?"},
    {"from": "Sam <sam@example.edu>", "subject": "Re: Coffee chat?",
     "body": "Sure, Tue 2-4 or Wed after 1.", "from_user": true},
    {"from": "Jordan Lee <jordan@example.com>", "subject": "Re: Coffee chat?",
     "body": "Tuesday at 2:30 works, see you then. Zoom or in person?"}
  ],
  "target_index": 2
}
```

Each message has `from`, `date`, `subject` and `body`, and optionally `to` (helps with the
group-mail rules E3, E4 and NR9) and `from_user` (sent by the mailbox owner, for NR1). An
optional top-level `message_id` is used in logs only.

```json
{"label": "acceptance", "needs_response": true,
 "reason": "D3: confirms a proposed time; NR3: asks Zoom or in person, requiring a response.",
 "model": "gemini-3.8-flash", "rules_version": "1.2", "latency_ms": 4613}
```

Errors never come with a label: `422` for a bad request (empty thread, `target_index`
outside it), `503` when Gemini is unreachable or still rate limited after 4 tries (waits of
about 1, 2 and 4 s), `502` when Gemini answers with an error or an invalid answer.

## Run it

```sh
# from src/classifier (needs gcloud application-default credentials)
GOOGLE_CLOUD_PROJECT=fixture-ac215-96dhbm uv run uvicorn main:app --port 8002 --reload

curl http://localhost:8002/health
uv run pytest
```

The web app finds it at `CLASSIFIER_URL` (default `http://localhost:8002`). In Docker:
`docker compose up --build classifier`.
