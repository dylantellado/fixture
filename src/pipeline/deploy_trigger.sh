#!/usr/bin/env bash
# Deploy the Cloud Function that starts the pipeline when a new data version lands.
#
# Usage (as a project owner, once; again after changing trigger/): src/pipeline/deploy_trigger.sh
#
# The function fires on every new object in the DVC bucket but only acts on
# pipeline-inputs/<id>/READY (see trigger/main.py). It runs as fixture-tuning, which
# already may start pipelines and act as itself (experiments/classifier_tuning/cloud/setup.sh).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/../../experiments/classifier_tuning/cloud/config.sh"
bucket="${DVC_BUCKET#gs://}"
number="$(gcloud projects describe "$PROJECT_ID" --format 'value(projectNumber)')"

echo "== APIs: Cloud Functions, Eventarc (Cloud Run, Build and Pub/Sub are already on)"
gcloud services enable cloudfunctions.googleapis.com eventarc.googleapis.com --project "$PROJECT_ID"

echo "== Permissions for bucket events"
# Cloud Storage publishes the bucket's events to Pub/Sub for Eventarc.
gcloud projects add-iam-policy-binding "$PROJECT_ID" --condition None >/dev/null \
  --member "serviceAccount:service-${number}@gs-project-accounts.iam.gserviceaccount.com" --role roles/pubsub.publisher
# The trigger delivers events to the function as the job account.
for role in roles/eventarc.eventReceiver roles/run.invoker; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --condition None >/dev/null \
    --member "serviceAccount:$JOB_SA" --role "$role"
done

echo "== Deploying fixture-pipeline-trigger ($REGION)"
gcloud functions deploy fixture-pipeline-trigger --gen2 --project "$PROJECT_ID" --region "$REGION" \
  --runtime python312 --source "$here/trigger" --entry-point on_new_data \
  --trigger-bucket "$bucket" --service-account "$JOB_SA" --trigger-service-account "$JOB_SA" \
  --build-service-account "projects/$PROJECT_ID/serviceAccounts/$BUILD_SA" \
  --memory 512Mi --max-instances 2 --set-env-vars "PROJECT_ID=$PROJECT_ID,REGION=$REGION,JOB_SA=$JOB_SA"
echo "Done. Upload a data version with src/pipeline/run_pipeline.sh (without --direct) to trigger a run."
