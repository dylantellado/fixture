#!/usr/bin/env bash
# Monitoring for the deployed classifier. Run once after the first deploy; safe to run
# again (each step creates what's missing and updates what exists).
#
# Usage:  src/classifier/cloud/monitoring.sh
#         ALERT_EMAIL=you@example.com src/classifier/cloud/monitoring.sh   # also the email alert
#
# What it sets up (all in Cloud Monitoring / Cloud Logging, project fixture-ac215-96dhbm):
#   1. Log-based metrics from the service's structured "classify" log line
#      (cloud/metrics/*.yaml): classifier_requests, classifier_errors, classifier_latency
#   2. Uptime check: GET /health every 5 minutes from 3 US regions. The service needs
#      authentication, so the check sends an OIDC token as the Monitoring service agent,
#      which gets roles/run.invoker on this one service (a Google-managed account, not a person).
#   3. Dashboard "Fixture classifier" (cloud/dashboard.json): request count, error rate,
#      p50/p95 latency, Cloud Run instances, response codes, uptime, recent log entries
#   4. Only if ALERT_EMAIL is set: an email channel to that address and an alert policy
#      (cloud/alert_error_rate.json): more than 20% of classify requests failed over
#      10 minutes, with at least 3 requests. Never add someone else's email without asking them.
set -euo pipefail
cd "$(dirname "$0")"
source config.sh

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format 'value(projectNumber)')"
MONITORING_AGENT="service-${PROJECT_NUMBER}@gcp-sa-monitoring-notification.iam.gserviceaccount.com"
API="https://monitoring.googleapis.com/v3/projects/$PROJECT_ID"
auth() { echo "Authorization: Bearer $(gcloud auth print-access-token)"; }

echo "== 1. Log-based metrics"
for file in metrics/*.yaml; do
  name="$(basename "$file" .yaml)"
  if gcloud logging metrics describe "$name" --project "$PROJECT_ID" >/dev/null 2>&1; then
    gcloud logging metrics update "$name" --config-from-file "$file" --project "$PROJECT_ID" >/dev/null
    echo "updated $name"
  else
    gcloud logging metrics create "$name" --config-from-file "$file" --project "$PROJECT_ID"
  fi
done

echo "== 2. Uptime check on /health"
# The Monitoring service agent exists only once something asks for it.
curl -sf -X POST -H "$(auth)" -H "x-goog-user-project: $PROJECT_ID" -H "Content-Type: application/json" -d '{}' \
  "https://serviceusage.googleapis.com/v1beta1/projects/$PROJECT_ID/services/monitoring.googleapis.com:generateServiceIdentity" >/dev/null
gcloud run services add-iam-policy-binding "$SERVICE" --region "$REGION" --project "$PROJECT_ID" \
  --member "serviceAccount:$MONITORING_AGENT" --role roles/run.invoker >/dev/null
UPTIME_NAME="$SERVICE /health"
UPTIME_ID="$(gcloud monitoring uptime list-configs --project "$PROJECT_ID" \
  --filter "displayName=\"$UPTIME_NAME\"" --format 'value(name.basename())')"
if [ -z "$UPTIME_ID" ]; then
  gcloud monitoring uptime create "$UPTIME_NAME" --project "$PROJECT_ID" \
    --resource-type cloud-run-revision \
    --resource-labels "project_id=$PROJECT_ID,service_name=$SERVICE,location=$REGION" \
    --protocol https --path /health \
    --service-agent-auth oidc-token \
    --matcher-content '"status":"ok"' --matcher-type contains-string \
    --period 5 --timeout 10 \
    --regions usa-iowa,usa-oregon,usa-virginia
  UPTIME_ID="$(gcloud monitoring uptime list-configs --project "$PROJECT_ID" \
    --filter "displayName=\"$UPTIME_NAME\"" --format 'value(name.basename())')"
fi
echo "uptime check: $UPTIME_ID"

echo "== 3. Dashboard"
DASHBOARD_FILE="$(mktemp)"
trap 'rm -f "$DASHBOARD_FILE"' EXIT
sed -e "s/__UPTIME_CHECK_ID__/$UPTIME_ID/" -e "s/__PROJECT_ID__/$PROJECT_ID/" dashboard.json > "$DASHBOARD_FILE"
DASHBOARD="$(gcloud monitoring dashboards list --project "$PROJECT_ID" \
  --filter 'displayName="Fixture classifier"' --format 'value(name)' | head -1)"
if [ -n "$DASHBOARD" ]; then
  # An update must carry the current etag.
  ETAG="$(gcloud monitoring dashboards describe "$DASHBOARD" --format 'value(etag)')"
  python3 - "$DASHBOARD_FILE" "$ETAG" <<'EOF'
import json, sys
path, etag = sys.argv[1], sys.argv[2]
config = json.load(open(path))
config["etag"] = etag
json.dump(config, open(path, "w"))
EOF
  gcloud monitoring dashboards update "$DASHBOARD" --config-from-file "$DASHBOARD_FILE" --format 'value(name)'
else
  DASHBOARD="$(gcloud monitoring dashboards create --project "$PROJECT_ID" --config-from-file "$DASHBOARD_FILE" \
    --format 'value(name)')"
fi
echo "dashboard: https://console.cloud.google.com/monitoring/dashboards/builder/${DASHBOARD##*/}?project=$PROJECT_ID"

echo "== 4. Error-rate alert"
if [ -z "${ALERT_EMAIL:-}" ]; then
  echo "ALERT_EMAIL not set: skipping the alert."
  exit 0
fi
# Reuse the email channel for this address if it exists.
CHANNEL="$(curl -sf -G -H "$(auth)" "$API/notificationChannels" \
  --data-urlencode "filter=type=\"email\" AND labels.email_address=\"$ALERT_EMAIL\"" \
  | python3 -c 'import json,sys; c=json.load(sys.stdin).get("notificationChannels",[]); print(c[0]["name"] if c else "")')"
if [ -z "$CHANNEL" ]; then
  CHANNEL="$(curl -sf -X POST -H "$(auth)" -H "Content-Type: application/json" "$API/notificationChannels" \
    -d "{\"type\": \"email\", \"displayName\": \"Fixture classifier alerts ($ALERT_EMAIL)\", \"labels\": {\"email_address\": \"$ALERT_EMAIL\"}}" \
    | python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])')"
fi
echo "notification channel: $CHANNEL"
POLICY_FILE="$(mktemp)"
trap 'rm -f "$DASHBOARD_FILE" "$POLICY_FILE"' EXIT
sed -e "s#__CHANNEL__#$CHANNEL#" alert_error_rate.json > "$POLICY_FILE"
POLICY="$(gcloud monitoring policies list --project "$PROJECT_ID" \
  --filter 'displayName="Fixture classifier: high error rate"' --format 'value(name)' | head -1)"
if [ -n "$POLICY" ]; then
  gcloud monitoring policies update "$POLICY" --policy-from-file "$POLICY_FILE" --format 'value(name)'
else
  gcloud monitoring policies create --project "$PROJECT_ID" --policy-from-file "$POLICY_FILE" --format 'value(name)'
fi
