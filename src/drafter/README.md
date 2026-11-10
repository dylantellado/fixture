# drafter

Drafts a calendar-aware reply to one scheduling email. The web app's **Draft reply** button
calls it; later a Gmail watcher will call the same endpoint for every new email that needs a
reply. The model writes the text, but the times come from code: free time is computed from
the user's busy times and rules, and every draft is checked before anyone sees it. A draft that
fails a check is rewritten once, then refused. **An unchecked draft is never returned.**

Read-only by design: the drafter **never sends email, creates Gmail drafts or changes a
calendar**, and it holds **no Google user credentials**. The caller sends everything in the
request. The drafter calls only Vertex AI (Gemini and embeddings) and, when no label is sent,
the [classifier](../classifier/README.md).

**Privacy:** the thread, past emails and busy times go to Vertex AI in our own GCP project
(`fixture-ac215-96dhbm`). Nothing is saved. Logs hold counts, labels, statuses, check names,
tokens and timing; never email text, subjects, addresses, names, the draft or times from it.

## How a draft is made

```
POST /draft ──► 1 classification ──► 2 rules + free time ──► 3 context ──► 4 Gemini ──► 5 checker ──► response
                 (sent, or ask the     (rules.py, slots.py:     (context.py:   (draft.py:    (checker.py,
                  classifier)           code, no LLM)            embeddings)    one call)     mentions.py: code)
                     │                       │                                                  │ fail
                     ▼                       ▼                                                  ▼
             no_reply_needed           no_free_time                                 retry once with the reasons,
             (no model call)           (no model call)                              then status "error", no draft
```

1. **Classification.** The request's `classification`, or a call to the classifier. If the email
   needs no reply (or the user sent it): `no_reply_needed`, no Gemini call.
2. **Rules and free time** ([`rules.py`](rules.py), [`slots.py`](slots.py)). The user's rules
   (defaults below) and busy times give the allowed meeting times. The meeting length comes from
   the email ("an hour", "45 minutes") or the default. If the email needs times offered and none
   are free: `no_free_time`, no Gemini call. Otherwise the model gets a short, spread-out list of
   allowed slots (up to two a day, morning and afternoon, on the first six free days), the free
   windows (to judge times the sender proposed) and the busy blocks (no details).
3. **Context** ([`context.py`](context.py)). The past emails with the sender are ranked by
   similarity to the thread with `gemini-embedding-001` (`RETRIEVAL_DOCUMENT` for past emails,
   `RETRIEVAL_QUERY` for the thread), and the top 5 go into the prompt. If embedding fails, the
   5 most recent are used, with a warning.
4. **Draft** ([`draft.py`](draft.py)). One Gemini call, temperature 0.2 (0.7 for Regenerate),
   structured JSON. The model chooses an action, picks slot ids (it can't invent a slot), names
   an accepted or confirmed time if any, and writes the text. What it should do depends on the label:

   | Label | The draft... |
   |---|---|
   | `new_request`, `reschedule` | offers 2-3 allowed slots on different days (reschedule: acknowledges, without naming the old time) |
   | `proposed_times` | accepts one of the sender's times only if it fits a free window; otherwise declines without repeating them and offers 2-3 slots |
   | `assistant_handoff` | writes to the assistant by name and offers 2-3 slots |
   | `acceptance` (with a question) | answers briefly; names the time only if it's on the calendar |
   | `none` ("still on?") | confirms if a busy block covers the meeting, otherwise asks them to confirm the time |

   Tone: short, warm, professional, a bit more casual with casual senders and more formal with
   recruiters and professors, signed with the user's first name. Past emails are used for
   preferences (mornings, phone calls) and never quoted or revealed.
5. **Checks** ([`checker.py`](checker.py), [`mentions.py`](mentions.py)), all in code:

   | Check | Passes when |
   |---|---|
   | `answer_well_formed` | the answer parsed: known slot ids, times with UTC offsets, a non-empty draft under 2,500 characters |
   | `offered_times_allowed` | every offered time passes `slots.check_time` (free, buffer, working hours, notice, horizon) |
   | `accepted_time_allowed` | an accepted time passes `slots.check_time` too |
   | `confirmed_time_on_calendar` | a meeting the draft confirms overlaps a busy event (the calendar shows it) |
   | `no_other_times_in_text` | every date or time written in the draft (weekdays, dates, "tomorrow", "2pm", "14:00", ranges, time zones) is one of the offered, accepted or confirmed times |
   | `times_written_in_text` | every offered or accepted time is written in the draft with its day, so the text and the structured answer agree |
   | `no_outside_contact_details` | every email address, link and phone number in the draft already appears in this thread (nothing from other threads, nothing made up) |

   If any check fails, the model gets one retry with the failures explained. If that also
   fails, the response is `status: "error"` with the checks and no draft text.

**Untrusted email text.** Every email goes into its own delimited block (`<target_email>`,
`<earlier_message>`, `<past_email>`), the model is told never to follow instructions inside
them, and text that tries to close a block is neutralized. The checker is the backstop: it reads
the model's answer, the calendar and the rules, so an email can't argue its way past it (only
the contact-details check reads the thread, to allow details already in it). See the
`prompt_injection` scenario.

## API

### `GET /health`

No model call. `{"status": "ok", "model": "gemini-3.8-flash", "embedding_model": "gemini-embedding-001", "rules_version": "1.0"}`

### `POST /draft`

Request (all fake; the full file is [`examples/new_request.json`](examples/new_request.json)):

```json
{
  "message_id": "example-new-request",
  "now": "2026-11-09T10:00:00-05:00",
  "user": {"name": "Sam Rivera", "email": "sam.rivera@example.edu", "timezone": "America/New_York"},
  "thread": [
    {"from": "Jordan Lee <jordan.lee@northbridge.example.com>", "to": "sam.rivera@example.edu",
     "date": "Mon, 09 Nov 2026 08:41:00 -0500", "subject": "Quick call about the analyst role?",
     "body": "Hi Sam,\n\nThanks for applying ... I'd love to set up a 30-minute call ... What does your availability look like over the next week or so?\n\nBest,\nJordan"}
  ],
  "target_index": 0,
  "classification": {"label": "new_request", "needs_response": true, "reason": "D1: asks to meet without specific times; NR1."},
  "busy": [
    {"start": "2026-11-10T09:00:00-05:00", "end": "2026-11-10T17:00:00-05:00"},
    {"start": "2026-11-11T10:00:00-05:00", "end": "2026-11-11T11:15:00-05:00"}
  ],
  "busy_until": "2026-11-23T10:00:00-05:00",
  "past_messages": [
    {"id": "past-1", "from": "Jordan Lee <jordan.lee@northbridge.example.com>", "to": "sam.rivera@example.edu",
     "date": "Tue, 20 Oct 2026 16:05:00 -0400", "subject": "Northbridge info session follow-up",
     "body": "Great meeting you at the info session! I usually do calls in the mornings ..."}
  ]
}
```

| Field | |
|---|---|
| `thread`, `target_index` | The thread, oldest first, and which message to reply to (later messages are ignored). Each message: `from`, `to`, `date`, `subject`, `body`, optional `id` and `from_user` (sent by the user). Bodies should already be cleaned (quoted replies and signatures removed); the web app does this. |
| `user` | `name` (for the sign-off), `email`, `timezone` (IANA name; times are computed and written in it). |
| `classification` | Optional `{label, needs_response, reason}`. Missing: the drafter calls the classifier at `CLASSIFIER_URL`. |
| `busy` | Busy intervals with UTC offsets, e.g. from Calendar's free/busy query. Overlapping ones are merged. |
| `busy_until` | Optional: the end of the period `busy` covers. No time after it is offered. |
| `past_messages` | Optional: messages exchanged with the sender in other threads (each needs an `id`). Up to 100; the top 5 by relevance are used. |
| `now` | Optional: defaults to the server's clock. |
| `rules` | Optional overrides for this draft (see [Rules](#rules)). Invalid ones get `422`. |
| `regenerate` | Optional: `true` for a differently worded draft (temperature 0.7). |
| `message_id` | Optional: only used in logs. |

Response (real output for the request above, `gemini-3.8-flash`):

```json
{
  "status": "drafted",
  "draft_text": "Hi Jordan,\n\nThanks for reaching out! I would love to connect and learn more about the team. Here are a few morning times that work well on my end:\n\n- Wed, Nov 11, 11:30 AM–12:00 PM EST\n- Thu, Nov 12, 10:00–10:30 AM EST\n- Fri, Nov 13, 10:00–10:30 AM EST\n\nPlease let me know if any of these work for you.\n\nBest,\nSam",
  "action": "offer_times",
  "offered_times": [
    {"start": "2026-11-11T11:30:00-05:00", "end": "2026-11-11T12:00:00-05:00", "label": "Wed, Nov 11, 11:30 AM–12:00 PM EST"},
    {"start": "2026-11-12T10:00:00-05:00", "end": "2026-11-12T10:30:00-05:00", "label": "Thu, Nov 12, 10:00–10:30 AM EST"},
    {"start": "2026-11-13T10:00:00-05:00", "end": "2026-11-13T10:30:00-05:00", "label": "Fri, Nov 13, 10:00–10:30 AM EST"}
  ],
  "accepted_time": null,
  "confirmed_time": null,
  "checks": [
    {"name": "answer_well_formed", "passed": true, "detail": "The answer is complete and every time in it is valid."},
    {"name": "offered_times_allowed", "passed": true, "detail": "All 3 offered times are free and follow your rules."},
    {"name": "accepted_time_allowed", "passed": true, "detail": "No time accepted."},
    {"name": "confirmed_time_on_calendar", "passed": true, "detail": "No existing meeting confirmed."},
    {"name": "no_other_times_in_text", "passed": true, "detail": "Every date or time in the draft (3) is one of its chosen times."},
    {"name": "times_written_in_text", "passed": true, "detail": "Every offered or accepted time is written in the draft."},
    {"name": "no_outside_contact_details", "passed": true, "detail": "No email addresses, links or phone numbers from outside this thread."}
  ],
  "context_used": [{"id": "past-1", "why": "Sender prefers morning calls.", "score": 0.763, "cited": true}],
  "warnings": [],
  "error": null,
  "error_type": null,
  "label": "new_request",
  "needs_response": true,
  "meeting_minutes": 30,
  "model": "gemini-3.8-flash",
  "rules_version": "1.0",
  "attempts": 1,
  "latency_ms": 5709,
  "usage": {"gemini_calls": 1, "input_tokens": 2833, "output_tokens": 239, "thinking_tokens": 0,
            "embedding_tokens": 227, "classifier_called": false}
}
```

| Field | |
|---|---|
| `status` | `drafted`; `no_reply_needed` (the label says no reply, or the user sent the email); `no_free_time` (the reply would need times and none fit the rules; `warnings` says why); `error` (see `error_type`: `checks_failed`, `gemini_unavailable`, `classifier_unavailable`). |
| `draft_text` | The reply; `""` unless `drafted`. |
| `action` | `offer_times`, `accept_time`, `confirm_meeting`, `answer_question` or `ask_question`. |
| `offered_times`, `accepted_time`, `confirmed_time` | Each `{start, end, label}` in the user's time zone. `confirmed_time` is an existing meeting the draft confirms (it's on the calendar). |
| `checks` | All seven checks with `passed` and a detail (details can quote the draft; they're never logged). On `checks_failed`, the second attempt's checks. |
| `context_used` | The past emails given to the model: `id`, `score` (similarity; `null` if picked by date), `cited` (the model says it used it) and a one-line `why`. |
| `warnings` | Soft problems, e.g. offered one time, the calendar was only checked until a date, ranking by date. |
| `rules_version` | The rules the draft followed (see [Rules](#rules)). |
| `usage` | Tokens for cost tracking. |

Valid requests always get `200` with a `status`. Invalid input (`target_index` outside the
thread, an unknown time zone, times without a UTC offset, unknown rule names) gets `422`; a bug
gets `500` with no details.

## Rules

[`rules/default_rules.json`](rules/default_rules.json), version `1.0`:

| Rule | Default |
|---|---|
| Busy calendar events | never offered or accepted. **In code, not a setting**: no override can change it. |
| `working_hours` | 08:00-20:00 in the user's time zone |
| `working_days` | every day |
| `min_notice_hours` | 24 |
| `buffer_minutes` | 15, before and after every busy event |
| `default_meeting_minutes` | 30, unless the email names a length |
| `horizon_days` | 14 (and never past `busy_until`) |
| `slot_step_minutes` | 30: slots start on the hour and half hour |

`rules.rules_for(email, request_overrides, store)` merges the defaults, the user's stored
overrides (`RulesStore`) and the request's overrides, later winning. Unknown names or invalid
values are refused. `rules_version` is the defaults' version, plus `+` and a hash of the
overrides when any apply (`1.0+3f9a1c2e`). To change a default, edit the JSON and bump `version`.

## Designed to be swapped later

| Today | Later | How to swap |
|---|---|---|
| The web app calls `POST /draft` when you click a button | A **Gmail watcher** drafts automatically for each new email that needs a reply | Call the same endpoint, or `pipeline.run(request, deps)` directly. The pipeline has no web-app assumptions: it takes a `DraftRequest` and returns the response dict. |
| The web app searches Gmail for the last ~10 threads with the sender and sends them as `past_messages` | A **persistent per-user inbox index** (like rag's per-user ChromaDB collections, kept fresh by the watcher) | Replace the body of `context.get_relevant_context(user, thread, target_index, past_messages, embedder)` with a query to the user's index; keep its signature and `ContextResult`. The same embedding model and task types are used today, so relevance stays comparable. The web app then stops sending `past_messages` (`draft_inputs.past_messages`). |
| `NoStoredRules`: everyone gets the defaults | A **settings page** where users edit their rules | Implement `RulesStore.overrides_for(email)` (e.g. reading the web app's database) and pass it as `Deps.rules_store` in `main.py`. Validation, merging and versioning already happen in `rules_for`. |
| One Gemini call per draft, model from `GEMINI_MODEL` | Another model or provider | `draft.ask_model` calls `deps.gemini.generate_json(system, user, schema, temperature)`; anything with that method works. The checker doesn't depend on the model. |
| Free/busy only (no event details) | Richer calendar data (e.g. to tell which event is the meeting being confirmed) | `confirmed_time_on_calendar` uses `slots.on_calendar`; extend the request with event ids if needed. |

## Files

| File | What it does |
|---|---|
| `main.py` | FastAPI app: `GET /health`, `POST /draft`; builds the real dependencies. |
| `pipeline.py` | The steps above as one function, `run(request, deps)`, and the one log line per draft. |
| `schemas.py` | Request and response models. |
| `rules.py`, `rules/default_rules.json` | Rules, overrides, versions. |
| `slots.py` | `check_time`, free slots and windows, candidates, meeting length, formatting. UTC math; DST-safe. |
| `context.py`, `embeddings.py` | Ranking past emails with Vertex AI embeddings. |
| `draft.py`, `gemini.py` | The prompt, the Gemini call (retries on rate limits), parsing the answer. |
| `checker.py`, `mentions.py` | The checks, and the date/time scanner they use. |
| `classifier_client.py` | Calls the classifier: plain HTTP locally, with a Google ID token on Cloud Run. |
| `logs.py` | Structured JSON logs with an allow-list of fields (same format as the classifier). |
| `scenarios/scenarios.json`, `run_scenarios.py` | 16 fake scenarios run against the real models; writes [`docs/evidence/ms3/draft_scenarios.md`](../../docs/evidence/ms3/draft_scenarios.md). |
| `examples/new_request.json` | The fake request above. |
| `test_*.py`, `conftest.py` | Tests with fake Gemini, embeddings and classifier. |

## Settings

| Variable | Default | |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | none (required to draft) | `fixture-ac215-96dhbm` |
| `GOOGLE_CLOUD_LOCATION` | `global` | Gemini 3.x Flash is served on the global endpoint for our project. |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Same as the classifier. |
| `GEMINI_THINKING_BUDGET` | `512` | Max thinking tokens per call (in Docker Compose: `DRAFTER_THINKING_BUDGET`). The scenarios used 0. |
| `EMBEDDING_MODEL`, `EMBEDDING_LOCATION` | `gemini-embedding-001`, `us-central1` | Same as rag and the api. |
| `CLASSIFIER_URL` | `http://localhost:8002` | Docker: `http://classifier:8002`. An `https://` URL (Cloud Run) is called with a Google ID token. |
| `CLASSIFIER_AUTH` | `auto` | `auto` (ID token for https), `id_token` or `none`. |
| `PORT` | `8003` | Only read by the Docker image's start command (Cloud Run sets 8080). |

Credentials are Google application-default credentials (`gcloud auth application-default login`).

**Calling the classifier on Cloud Run.** With `CLASSIFIER_URL=https://fixture-classifier-622192804476.us-east1.run.app`,
each call carries an ID token. On Cloud Run it comes from the metadata server for the
classifier's URL; locally, from your gcloud user credentials (the same kind of token `gcloud
auth print-identity-token` prints). Either way the identity needs `roles/run.invoker` on the
classifier (a project owner already has it).

## Run it

```sh
# from src/drafter (needs gcloud application-default credentials)
GOOGLE_CLOUD_PROJECT=fixture-ac215-96dhbm uv run uvicorn main:app --port 8003 --reload

curl http://localhost:8003/health
curl -s -X POST http://localhost:8003/draft -H "Content-Type: application/json" -d @examples/new_request.json

uv run pytest                                   # 135 tests, no network
uv run python run_scenarios.py                  # 16 fake scenarios against the real models (~5 cents)
```

The web app finds it at `DRAFTER_URL` (default `http://localhost:8003`). With Docker:
`docker compose up --build classifier drafter frontend` (the frontend also needs the api;
see the root README).

**Cloud Run.** The image is ready (listens on `$PORT`, `uv sync --locked --no-dev`, only this
folder's code) but not deployed. A deployment would mirror the classifier's: its own service
account with `roles/aiplatform.user` and `roles/logging.logWriter`, plus `roles/run.invoker` on
the classifier, `--no-allow-unauthenticated`, and the web app calling it with an ID token.

## Logs

One JSON line per `/draft` (`event: "draft"`), INFO or ERROR:

```json
{"severity": "INFO", "message": "draft: status=drafted label=new_request attempts=1 latency_ms=3872",
 "logger": "drafter", "event": "draft", "message_id": "scenario-new_request_recruiter", "status": "drafted",
 "label": "new_request", "needs_response": true, "classification_source": "request", "action": "offer_times",
 "thread_length": 1, "busy_count": 15, "past_messages": 0, "context_method": "none", "meeting_minutes": 30,
 "meeting_minutes_source": "email", "allowed_slots": 12, "free_windows": 20, "offered_count": 3,
 "accepted": false, "confirmed": false, "checks_passed": 7, "checks_failed": 0, "attempts": 1,
 "gemini_calls": 1, "input_tokens": 2973, "output_tokens": 206, "thinking_tokens": 0, "embedding_tokens": 0,
 "latency_ms": 3872, "gemini_ms": 3860, "context_ms": 0, "model": "gemini-3.8-flash",
 "embedding_model": "gemini-embedding-001", "rules_version": "1.0", "rules_custom": false, "temperature": 0.2}
```

Failed checks are logged by name (`failed_checks`), never with their details. As in the
classifier, `logs.py` drops any field not in `ALLOWED_FIELDS`, and stack traces keep the
exception type but not its message. `test_logs.py` puts a marker in every text field (thread,
past emails, user, the model's draft) and checks that none reaches a log line, on success,
failed checks, Gemini, embedding and classifier errors, and bugs.

## Cost

From the scenario run ([`draft_scenarios.md`](../../docs/evidence/ms3/draft_scenarios.md)):
about 2,900 input and 200-250 output tokens per draft, about $0.003 per draft at Gemini 3.8
Flash's introductory price ($0.006 from 2027), plus about $0.003 when the drafter has to call
the classifier. Embeddings are a few hundred tokens ($0.15 per 1M), well under a hundredth of a
cent. `no_reply_needed` and `no_free_time` cost nothing. A retry doubles the Gemini part.
