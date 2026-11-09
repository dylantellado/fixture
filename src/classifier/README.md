# classifier

Labels one email with Gemini (Vertex AI), following
[`docs/data/labeling_rules.md`](../../docs/data/labeling_rules.md): one of the six labels
plus `needs_response`, with a one-line reason. The web app uses it to label the signed-in
user's recent Gmail emails. It only reads what it's sent: it never touches Gmail or Calendar.

It runs locally (below, or in Docker Compose) and is deployed to **Cloud Run** at
https://fixture-classifier-622192804476.us-east1.run.app (authentication required; see
[Deployed service](#deployed-service-cloud-run) and [Monitoring](#monitoring)).

**Privacy:** email text is sent to Gemini in our own GCP project (`fixture-ac215-96dhbm`).
This service never logs or saves email text, subjects, senders or Gemini's reason. Logs hold
message ids, labels, timing and token counts only.

## Files

| File | What it does |
|------|--------------|
| `main.py` | FastAPI app: `GET /health`, `POST /classify`, request checks, logging. |
| `prompt.py` | Builds the prompt (no network). Same function names as `experiments/gemini_baseline/prompt.py`, for comparison; nothing is imported from `experiments/`. |
| `gemini.py` | Calls Gemini with structured JSON output, temperature 0; retries rate limits with backoff; checks the answer. |
| `logs.py` | Structured JSON logs for Cloud Logging, with an allow-list of fields (see [Logs](#logs)). |
| `Dockerfile` | Two-stage image: `uv sync --locked --no-dev`, then only the virtualenv and code. Listens on `$PORT` (Cloud Run) or 8002. |
| `deploy.sh` | Build with Cloud Build and deploy to Cloud Run: the one command for every (re)deploy. |
| `cloud/` | `config.sh` (project, region, names), `setup.sh` (one-time: APIs, service accounts, registry), `build_context.sh` (the image's build folder from git), `cloudbuild.yaml`, `monitoring.sh` with `metrics/`, `dashboard.json` and `alert_error_rate.json`. |
| `examples/` | Fake `/classify` requests: proposed times, cold sales pitch, prompt-injection newsletter, acceptance. |
| `test_prompt.py`, `test_main.py`, `test_logs.py` | Tests, with fake threads. Gemini is never called. `test_logs.py` checks that no email text reaches a log line, startup with the bundled rules file, and the build folder. |

## Settings

| Variable | Default | |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | none (required to classify) | `fixture-ac215-96dhbm` |
| `GOOGLE_CLOUD_LOCATION` | `global` | Gemini 3.x Flash models are served on the global endpoint for our project; `us-central1` returned 404 (2026-10-29). |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Checked with a test call on 2026-10-29. |
| `GEMINI_THINKING_BUDGET` | `128` | Max thinking tokens per email. The baseline showed the same accuracy as the model's default for about a third less cost and latency. |
| `RULES_PATH` | `docs/data/labeling_rules.md` | The Docker image sets `/app/labeling_rules.md` (the Cloud Run image has the file inside); Docker Compose mounts the repo's file at `/rules/labeling_rules.md` instead. |
| `PORT` | `8002` | Only used by the Docker image's start command. Cloud Run sets 8080. |

Credentials are Google application-default credentials: run
`gcloud auth application-default login` once. No API keys, no `.env`, no `secrets/`. On
Cloud Run the service uses its own service account instead.

## The prompt

- **System instruction:** short instructions, then the labeling rules file read at startup,
  without the sections that must never reach the model: "Not adopted" (proposals) and
  "Change log" (`EXCLUDED_SECTIONS` in `prompt.py`, matched by heading). Training answers
  live in `docs/data/training_conflicts.md` (since rules v1.3), which is never read. The
  rules version (e.g. `1.5`) is read from the file's `**Version X.Y` line and returned with
  every label. The service won't start if the file is missing, has no version, or doesn't
  have exactly one heading for each excluded section: when the rules file is reorganized,
  update `EXCLUDED_SECTIONS` on purpose. A test checks that no training message id (from the
  training threads, the rules file or `training_conflicts.md`) reaches the prompt.
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
{"status": "ok", "model": "gemini-3.8-flash", "rules_version": "1.5"}
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
 "model": "gemini-3.8-flash", "rules_version": "1.5", "latency_ms": 4613}
```

Errors never come with a label: `422` for a bad request (empty thread, `target_index`
outside it), `503` when Gemini is unreachable or still rate limited after 4 tries (waits of
about 1, 2 and 4 s), `502` when Gemini answers with an error or an invalid answer, `500`
for a bug in this service. On Cloud Run, a request without a valid identity token gets
`403` from Cloud Run before it reaches the service.

## Run it

```sh
# from src/classifier (needs gcloud application-default credentials)
GOOGLE_CLOUD_PROJECT=fixture-ac215-96dhbm uv run uvicorn main:app --port 8002 --reload

curl http://localhost:8002/health
uv run pytest
```

The web app finds it at `CLASSIFIER_URL` (default `http://localhost:8002`). In Docker:
`docker compose up --build classifier`.

Try the examples locally:

```sh
curl -s -X POST http://localhost:8002/classify -H "Content-Type: application/json" \
  -d @examples/proposed_times.json
```

## Logs

Every log line is one JSON object on stdout, which Cloud Logging parses: `severity`,
`message` and `time`, plus fields kept in `jsonPayload`. One line per `/classify`:

```json
{"severity": "INFO", "message": "classified: label=none needs_response=false latency_ms=1454",
 "time": "2026-11-09T20:09:14.480Z", "logger": "classifier", "event": "classify",
 "message_id": "example-injection-newsletter", "thread_length": 1, "target_index": 0,
 "model": "gemini-3.8-flash", "rules_version": "1.5", "outcome": "ok", "status": 200,
 "label": "none", "needs_response": false, "latency_ms": 1454, "attempts": 1,
 "input_tokens": 3633, "output_tokens": 49, "thinking_tokens": 0}
```

| `event` | When | Fields |
|---|---|---|
| `startup` | each instance start | `model`, `project`, `location`, `thinking_budget`, `rules_version`, `rules_sha256`, `rules_path` |
| `classify` | each valid `/classify` | `outcome` (`ok` or `error`), `status`, `message_id` (if sent), `thread_length`, `target_index`, `model`, `rules_version`, `latency_ms`; on success `label`, `needs_response`, `attempts`, token counts; on error `error_type` (`rate_limited`, `api_error`, `unreachable`, `invalid_answer`, `no_project`, `client_error`, or the exception type for a bug) and `gemini_code` (ERROR severity) |
| `gemini_retry` | a Gemini call failed and will be retried | `attempts`, `gemini_code`, `error_type` (WARNING) |

**No email text in logs:** email text, subjects, senders, recipients and Gemini's reason are
never passed to the logger. As a second guard, `logs.py` drops any field that isn't in
`ALLOWED_FIELDS`, and stack traces keep the exception type but not its message.
`test_logs.py` sends a thread with a marker in every field and checks that no marker reaches
any log line, on success, Gemini errors, bugs and retries. uvicorn's own messages are JSON
too; its access log is off (Cloud Run logs every request).

To check which rules a running service uses, compare the startup line's `rules_sha256` with
`shasum -a 256 docs/data/labeling_rules.md`.

## Deployed service (Cloud Run)

| | |
|---|---|
| URL | https://fixture-classifier-622192804476.us-east1.run.app |
| Project, region | `fixture-ac215-96dhbm`, `us-east1` (Gemini is still called on the `global` endpoint) |
| Service account | `fixture-classifier@fixture-ac215-96dhbm.iam.gserviceaccount.com`: only `roles/aiplatform.user` and `roles/logging.logWriter` |
| Image | `us-east1-docker.pkg.dev/fixture-ac215-96dhbm/fixture/classifier:<git commit>` (Artifact Registry repo `fixture`, newest 5 kept) |
| Scaling | min 0, max 2 instances; concurrency 20; 1 vCPU, 512 MiB; timeout 150 s; CPU only during requests |
| Access | authentication required (`--no-allow-unauthenticated`) |

The settings and the reason for each are commented in [`deploy.sh`](deploy.sh). Shared names
(project, region, service accounts) are in [`cloud/config.sh`](cloud/config.sh).

### What's in the image

`cloud/build_context.sh` makes the build folder from the **last commit**: this folder's
`Dockerfile`, `pyproject.toml`, `uv.lock`, `.python-version` and non-test `.py` files, plus
`docs/data/labeling_rules.md` from the same commit, saved as `labeling_rules.md`. Nothing
else from the repo is sent to Cloud Build, so `data/` and `training_conflicts.md` can't end
up in the image (`test_logs.py` checks this). The image tag is the commit, and the
service's labels record the commit and the rules file's sha256.

### Access

Callers need `roles/run.invoker` on the service and a Google identity token. Nobody outside
the project has it yet; the uptime check's Monitoring service agent is the only invoker.

Grant a person access (any Google account; replace the email):

```sh
gcloud run services add-iam-policy-binding fixture-classifier \
  --region us-east1 --project fixture-ac215-96dhbm \
  --member "user:PERSON@example.com" --role roles/run.invoker
```

Remove it again with `remove-iam-policy-binding` and the same flags. List who has access with
`gcloud run services get-iam-policy fixture-classifier --region us-east1`.

### Call it

The person signs in with `gcloud auth login` (their own account) and runs:

```sh
URL=https://fixture-classifier-622192804476.us-east1.run.app
TOKEN=$(gcloud auth print-identity-token)

curl -H "Authorization: Bearer $TOKEN" $URL/health
# {"status":"ok","model":"gemini-3.8-flash","rules_version":"1.5"}

# from the repo root
curl -X POST $URL/classify -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d @src/classifier/examples/proposed_times.json
# {"label":"proposed_times","needs_response":true,"reason":"D2, PR: proposes specific meeting times; ...",
#  "model":"gemini-3.8-flash","rules_version":"1.5","latency_ms":3650}
```

Without the header the answer is `403`. Tokens last an hour. The first request after the
service has scaled to zero takes a few seconds more (cold start). More requests and their
real responses: [`docs/evidence/ms3/cloud_run_curl.md`](../../docs/evidence/ms3/cloud_run_curl.md).

### Deploy and redeploy

First time, as a project owner (each script is safe to run again):

```sh
src/classifier/cloud/setup.sh        # APIs, Artifact Registry repo, the two service accounts, build bucket
src/classifier/deploy.sh             # build + deploy
ALERT_EMAIL=you@example.com src/classifier/cloud/monitoring.sh   # metrics, dashboard, uptime check, alert
```

Every redeploy after that is one command, from a clean checkout of the commit to deploy:

```sh
src/classifier/deploy.sh
```

It refuses to run with uncommitted changes in `src/classifier` or the rules file, builds the
image with Cloud Build (no local Docker needed; skipped if that commit's image exists),
deploys a new revision and prints the URL. It takes about a minute. A rules change is
deployed the same way: commit it, then run `deploy.sh`.

Roll back to an earlier revision:

```sh
gcloud run revisions list --service fixture-classifier --region us-east1
gcloud run services update-traffic fixture-classifier --region us-east1 --to-revisions REVISION=100
```

## Monitoring

Created by [`cloud/monitoring.sh`](cloud/monitoring.sh) from the files in `cloud/`, so it can be
recreated.

| What | How | Link |
|---|---|---|
| Logs | The structured lines above, plus Cloud Run's request logs (every HTTP request with status and latency) | [Logs Explorer](https://console.cloud.google.com/logs/query;query=resource.type%3D%22cloud_run_revision%22%0Aresource.labels.service_name%3D%22fixture-classifier%22%0AjsonPayload.event%3D%22classify%22?project=fixture-ac215-96dhbm) |
| Log-based metrics | `classifier_requests` (counter, by `outcome` and `label`), `classifier_errors` (counter, by `error_type` and `status`), `classifier_latency` (distribution of `latency_ms`) from the `classify` line ([`cloud/metrics/`](cloud/metrics/)) | Logging > Log-based metrics |
| Dashboard "Fixture classifier" | Classify requests/min by outcome, error rate (%), latency p50/p95, Cloud Run instances (active/idle), all requests by response code, uptime, recent classify log entries ([`cloud/dashboard.json`](cloud/dashboard.json)) | [Dashboard](https://console.cloud.google.com/monitoring/dashboards/builder/6bbe0f64-0c52-43a4-8bf8-80029a1dc8d4?project=fixture-ac215-96dhbm) |
| Uptime check | `GET /health` every 5 minutes from Iowa, Oregon and Virginia, expecting `"status":"ok"`, with an OIDC token from the Monitoring service agent (which has `roles/run.invoker` on this service only) | [Uptime checks](https://console.cloud.google.com/monitoring/uptime?project=fixture-ac215-96dhbm) |
| Alert | More than 20% of classify requests failed over 10 minutes, with at least 3 requests; emails `ALERT_EMAIL` (Dylan) ([`cloud/alert_error_rate.json`](cloud/alert_error_rate.json)) | [Alerting](https://console.cloud.google.com/monitoring/alerting?project=fixture-ac215-96dhbm) |

You need access to the project to open these links. Example Logs Explorer queries:

```
-- every classify request
resource.type="cloud_run_revision"
resource.labels.service_name="fixture-classifier"
jsonPayload.event="classify"

-- failures only, with their error_type
resource.type="cloud_run_revision"
resource.labels.service_name="fixture-classifier"
jsonPayload.outcome="error"

-- slow calls
resource.type="cloud_run_revision"
resource.labels.service_name="fixture-classifier"
jsonPayload.latency_ms>10000

-- which rules each instance started with
resource.type="cloud_run_revision"
resource.labels.service_name="fixture-classifier"
jsonPayload.event="startup"
```

From the command line:

```sh
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="fixture-classifier" AND jsonPayload.event="classify"' \
  --limit 10 --format "table(timestamp, severity, jsonPayload.outcome, jsonPayload.label, jsonPayload.latency_ms, jsonPayload.input_tokens)"
```

**Cost:** about $0.003 per classified email now and $0.006 from 2027-01-01, when Gemini 3.8
Flash's introductory price ends. Gemini is about 98% of it; Cloud Run, logging, metrics, the
uptime check and the dashboard stay inside the free tiers at our usage. That's about $3 a
month for 1,000 emails, and $0 when idle. Details:
[`docs/evidence/ms3/README.md`](../../docs/evidence/ms3/README.md#cost).
