#!/usr/bin/env bash
# One-time Google Cloud setup for tuning runs on Vertex AI. Safe to run again.
#
# Usage (as a project owner, after `wandb login`): experiments/classifier_tuning/cloud/setup.sh
#
# Sets up in project fixture-ac215-96dhbm:
#   1. Secret Manager API (Vertex AI, Cloud Build and Artifact Registry are already on,
#      from src/classifier/cloud/setup.sh)
#   2. Secret "wandb-api-key", holding your W&B key (read from your `wandb login`; never printed)
#   3. Service account fixture-tuning, what tuning jobs and the pipeline run as. Roles:
#      Vertex AI user (call Gemini, run pipelines), log writer, read and write objects in the
#      DVC bucket (inputs, pipeline run folders; the bucket keeps old versions), read that
#      one secret.
set -euo pipefail
cd "$(dirname "$0")"
source config.sh

echo "== 1. Enabling Secret Manager"
gcloud services enable secretmanager.googleapis.com --project "$PROJECT_ID"
# A newly enabled API can take a few minutes to work everywhere: wait until it answers.
for attempt in $(seq 1 30); do
  if gcloud secrets list --project "$PROJECT_ID" --limit 1 >/dev/null 2>&1; then break; fi
  [ "$attempt" = 30 ] && { echo "Secret Manager still not ready; rerun this script in a few minutes" >&2; exit 1; }
  echo "   waiting for Secret Manager to be ready ($attempt/30)..."
  sleep 10
done

echo "== 2. Secret: $WANDB_SECRET"
if ! gcloud secrets describe "$WANDB_SECRET" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud secrets create "$WANDB_SECRET" --project "$PROJECT_ID" --replication-policy automatic
fi
# Add the key from your local W&B login as a new version (piped, never echoed).
(cd .. && uv run python -W ignore -c "import wandb, sys; sys.stdout.write(wandb.Api().api_key)") \
  | gcloud secrets versions add "$WANDB_SECRET" --project "$PROJECT_ID" --data-file=- >/dev/null

echo "== 3. Job service account: $JOB_SA"
if ! gcloud iam service-accounts describe "$JOB_SA" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${JOB_SA%%@*}" --project "$PROJECT_ID" \
    --display-name "Fixture tuning runs (Vertex AI custom jobs)"
  sleep 10  # a new account takes a few seconds before it can get roles
fi
for role in roles/aiplatform.user roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$JOB_SA" --role "$role" \
    --condition None >/dev/null
done
# Read the tuning inputs, and (for the pipeline) write each run's folder and pipeline root.
gcloud storage buckets add-iam-policy-binding "$DVC_BUCKET" \
  --member "serviceAccount:$JOB_SA" --role roles/storage.objectUser >/dev/null
# The pipeline runs its steps as this same account, so it must be allowed to act as itself.
gcloud iam service-accounts add-iam-policy-binding "$JOB_SA" --project "$PROJECT_ID" \
  --member "serviceAccount:$JOB_SA" --role roles/iam.serviceAccountUser >/dev/null
gcloud secrets add-iam-policy-binding "$WANDB_SECRET" --project "$PROJECT_ID" \
  --member "serviceAccount:$JOB_SA" --role roles/secretmanager.secretAccessor >/dev/null

echo "Done. Next: experiments/classifier_tuning/cloud/run_vertex_job.sh"
