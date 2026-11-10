# Milestone 3 evidence: classifier on Cloud Run

The `classifier` service (labels one email with Gemini) is deployed to Cloud Run with
Cloud Logging and Cloud Monitoring. How to call, redeploy and monitor it:
[`src/classifier/README.md`](../../../src/classifier/README.md#deployed-service-cloud-run).

| | |
|---|---|
| Service | `fixture-classifier`, Cloud Run, region `us-east1`, project `fixture-ac215-96dhbm` |
| URL | https://fixture-classifier-622192804476.us-east1.run.app (requires a Google identity token with `roles/run.invoker`) |
| Runs as | `fixture-classifier@fixture-ac215-96dhbm.iam.gserviceaccount.com` (only `roles/aiplatform.user` and `roles/logging.logWriter`) |
| Image | `us-east1-docker.pkg.dev/fixture-ac215-96dhbm/fixture/classifier:<git commit>`, built by Cloud Build as `fixture-builder@…`, with the exact `docs/data/labeling_rules.md` from that commit inside |
| Settings | min 0 / max 2 instances, 1 vCPU, 512 MiB, concurrency 20, timeout 150 s, Gemini `gemini-3.8-flash` on the `global` endpoint, thinking budget 128 |
| Deploy / redeploy | `src/classifier/deploy.sh` (one command; first time also `cloud/setup.sh`, then `cloud/monitoring.sh`) |

## Files

| File | What it shows |
|---|---|
| [`cloud_run_curl.md`](cloud_run_curl.md) | The exact curl commands and responses: 403 without a token, `/health`, `/classify` on a proposed-times email, a cold sales pitch, a prompt-injection newsletter and an acceptance, and a 422 for an invalid request. |
| [`cloud_logging_entries.json`](cloud_logging_entries.json) | The structured Cloud Logging entries for those requests and the instance's startup line (rules version 1.5, rules sha256 `4473a869…`, which matches `shasum -a 256 docs/data/labeling_rules.md` at that commit). No email text, subject, address or reason. |
| [`cloud_run_service.txt`](cloud_run_service.txt) | The deployed configuration (`gcloud run services describe`), who can invoke it (only the uptime check's Monitoring service agent so far) and the runtime service account's roles. |
| [`draft_scenarios.md`](draft_scenarios.md) | The drafter (Draft reply, not deployed) on 16 fake scenarios against the real Gemini: every label, a fully booked calendar, a sender proposing only busy times, a prompt-injection email, casual vs formal senders, time zones and a DST change. Status, offered times, checks, cost and the full draft for each; every returned time re-checked independently. Made by `src/drafter/run_scenarios.py`. |
| `*.png` | Screenshots, see the checklist below. |

## Monitoring

| What | Where |
|---|---|
| Structured logs: one JSON line per `/classify` (outcome, label, needs_response, latency_ms, attempts, input/output/thinking tokens, model, rules_version, error_type, status, message_id if given), a startup line (model, rules version and sha256), Gemini retries. Cloud Run's own request logs record every HTTP request (status, latency). | [Logs Explorer, classify entries](https://console.cloud.google.com/logs/query;query=resource.type%3D%22cloud_run_revision%22%0Aresource.labels.service_name%3D%22fixture-classifier%22%0AjsonPayload.event%3D%22classify%22?project=fixture-ac215-96dhbm) |
| Log-based metrics: `classifier_requests` (by outcome, label), `classifier_errors` (by error_type, status), `classifier_latency` (distribution, ms) | Logging > Log-based metrics |
| Dashboard "Fixture classifier": classify requests/min, error rate, p50/p95 latency, Cloud Run instances, all requests by response code, uptime, recent classify log entries | [Dashboard](https://console.cloud.google.com/monitoring/dashboards/builder/6bbe0f64-0c52-43a4-8bf8-80029a1dc8d4?project=fixture-ac215-96dhbm) |
| Uptime check `fixture-classifier /health`: every 5 min from Iowa, Oregon and Virginia, authenticated with an OIDC token, expects `"status":"ok"` | [Uptime checks](https://console.cloud.google.com/monitoring/uptime?project=fixture-ac215-96dhbm) |
| Alert "Fixture classifier: high error rate": more than 20% of classify requests failed over 10 minutes (at least 3 requests); emails Dylan only | [Alerting](https://console.cloud.google.com/monitoring/alerting?project=fixture-ac215-96dhbm) |

Everything above is created by [`src/classifier/cloud/monitoring.sh`](../../../src/classifier/cloud/monitoring.sh)
from the files next to it, so it can be recreated in another project.

## Cost

Measured per request (the four example requests and the rules v1.5 baseline run agree):
about 3,700 input tokens (the rules are most of the prompt), 40 to 50 output tokens, 0
thinking tokens at budget 128, and 1.5 to 3.7 s per call.

Prices from the Cloud Billing catalog (checked 2026-11-09). Gemini 3.8 Flash on the
global endpoint lists at $1.50 per 1M input and $7.50 per 1M output tokens. Google's
pricing page offers an introductory $0.75 / $3.75 through 2026-12-31, so the cost per
email doubles on 2027-01-01.

| Per classified email | Now (introductory price) | From 2027-01-01 |
|---|---|---|
| Gemini input, ~3,700 tokens | $0.0028 | $0.0056 |
| Gemini output, ~45 tokens | $0.0002 | $0.0003 |
| Cloud Run, ~2.5 s of 1 vCPU + 0.5 GiB at $0.000024/vCPU-s + $0.0000025/GiB-s | ≤ $0.00006 (free tier) | ≤ $0.00006 (free tier) |
| **Total** | **≈ $0.003** | **≈ $0.006** |

Gemini is about 98% of the cost. Cloud Run bills only while a request is handled (min
instances 0, request-based billing), and its monthly free tier (180,000 vCPU-s,
360,000 GiB-s, 2M requests) covers about 70,000 classify requests.

**Monthly at low usage** (1,000 classified emails, e.g. two people using the dashboard most
days; the web app caches labels, so each email is classified once):

| Item | Usage | Cost |
|---|---|---|
| Gemini | 1,000 calls | ~$3 (from 2027: ~$6) |
| Cloud Run | ~2,500 vCPU-s for classify + ~26,000 `/health` checks | $0, inside the free tier |
| Uptime check | 3 regions x 12/hour = ~26,000 executions | $0 (1M free per project) |
| Cloud Logging | ~1 KB per request | $0 (50 GiB free per project) |
| Log-based metrics | a few hundred KB of metric data | $0 (150 MiB free) |
| Alert policy | 1 condition | $0: the catalog has no SKU for alert conditions; evaluations return ~1 time series (1M free) |
| Artifact Registry | 91 MB for two images (shared layers); old images cleaned up | $0 (0.5 GB free) |
| Cloud Build | ~1 build-minute per deploy | $0 (2,500 minutes free) |
| **Total** | | **~$3 per month (~$6 from 2027)** |

Idle cost is $0. A teaching-staff check of 100 requests costs about $0.30.

## Screenshot checklist

Save each image in this folder (`docs/evidence/ms3/`) with the name given.

1. **`curl_terminal.png`: terminal, curl against the deployed service.** From the repo root:

   ```sh
   URL=https://fixture-classifier-622192804476.us-east1.run.app
   TOKEN=$(gcloud auth print-identity-token)
   curl -s -o /dev/null -w "%{http_code}\n" $URL/health          # 403: no token
   curl -s -H "Authorization: Bearer $TOKEN" $URL/health; echo
   curl -s -X POST $URL/classify -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" -d @src/classifier/examples/injection_newsletter.json | python3 -m json.tool
   ```

   Capture the commands and output in one shot: the `.run.app` URL, the 403, the health
   JSON and the label JSON. Don't `echo $TOKEN`.
2. **`cloud_run_service.png`: the Cloud Run service page.** Open the
   [service](https://console.cloud.google.com/run/detail/us-east1/fixture-classifier/metrics?project=fixture-ac215-96dhbm).
   Show the name, region us-east1, the URL, the green status and the Metrics tab (request
   count, latency, instance count). A second shot of the "Security" tab showing
   "Require authentication" would also help.
3. **`logs_explorer_entry.png`: Logs Explorer with one structured entry expanded.** Open
   [Logs Explorer](https://console.cloud.google.com/logs/query;query=resource.type%3D%22cloud_run_revision%22%0Aresource.labels.service_name%3D%22fixture-classifier%22%0AjsonPayload.event%3D%22classify%22?project=fixture-ac215-96dhbm)
   (the query is filled in), click one entry, and expand `jsonPayload` so `label`,
   `needs_response`, `latency_ms`, the token counts, `rules_version` and `message_id` show.
4. **`monitoring_dashboard.png`: the "Fixture classifier" dashboard.** Send a few requests
   first (step 1, or the four examples), wait 2 to 3 minutes, then open the
   [dashboard](https://console.cloud.google.com/monitoring/dashboards/builder/6bbe0f64-0c52-43a4-8bf8-80029a1dc8d4?project=fixture-ac215-96dhbm)
   with the time range at "1 hour". Show the request, error-rate, latency and instance charts.
5. Optional: **`uptime_check.png`** ([uptime checks](https://console.cloud.google.com/monitoring/uptime?project=fixture-ac215-96dhbm), the check passing in all three regions) and **`alert_policy.png`** ([alerting](https://console.cloud.google.com/monitoring/alerting?project=fixture-ac215-96dhbm)).
