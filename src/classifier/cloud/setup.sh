#!/usr/bin/env bash
# One-time Google Cloud setup for deploying the classifier. Safe to run again: each
# step skips what already exists.
#
# Usage (from anywhere, as a project owner): src/classifier/cloud/setup.sh
#
# What it sets up in project fixture-ac215-96dhbm:
#   1. APIs: Cloud Run, Cloud Build, Artifact Registry, Logging, Monitoring, Vertex AI, IAM
#   2. Artifact Registry repository "fixture" (Docker) in $REGION, keeping the 5 newest images
#   3. Service account fixture-classifier: what the service runs as.
#      Roles: Vertex AI user (call Gemini) and log writer. Nothing else.
#   4. Service account fixture-builder: what Cloud Build runs as.
#      Roles: write to the "fixture" repository, read the uploaded source, write build logs.
#   5. The bucket Cloud Build uploads source to.
# It never grants anyone access to the service; see the README's "Access" section.
set -euo pipefail
cd "$(dirname "$0")"
source config.sh

echo "== 1. Enabling APIs (takes a minute the first time)"
gcloud services enable --project "$PROJECT_ID" \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  logging.googleapis.com monitoring.googleapis.com aiplatform.googleapis.com iam.googleapis.com

echo "== 2. Artifact Registry repository: $REPOSITORY ($REGION)"
if ! gcloud artifacts repositories describe "$REPOSITORY" --location "$REGION" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud artifacts repositories create "$REPOSITORY" --repository-format docker \
    --location "$REGION" --project "$PROJECT_ID" --description "Fixture service images"
fi
# Delete images that are older than 30 days and not among the 5 newest (kept for
# rollbacks), so storage stays under the free 0.5 GB.
cat > "${TMPDIR:-/tmp}/fixture-cleanup-policy.json" <<'EOF'
[
  {"name": "keep-5-newest", "action": {"type": "Keep"}, "mostRecentVersions": {"keepCount": 5}},
  {"name": "delete-old", "action": {"type": "Delete"}, "condition": {"tagState": "any", "olderThan": "30d"}}
]
EOF
gcloud artifacts repositories set-cleanup-policies "$REPOSITORY" --location "$REGION" --project "$PROJECT_ID" \
  --policy "${TMPDIR:-/tmp}/fixture-cleanup-policy.json" --no-dry-run >/dev/null

create_sa() {  # create_sa EMAIL DISPLAY_NAME
  local name="${1%%@*}"
  if ! gcloud iam service-accounts describe "$1" --project "$PROJECT_ID" >/dev/null 2>&1; then
    gcloud iam service-accounts create "$name" --project "$PROJECT_ID" --display-name "$2"
    sleep 10  # a new service account takes a few seconds before it can get roles
  fi
}

grant_project_role() {  # grant_project_role EMAIL ROLE
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$1" --role "$2" \
    --condition None >/dev/null
}

echo "== 3. Runtime service account: $RUNTIME_SA"
create_sa "$RUNTIME_SA" "Fixture classifier (Cloud Run runtime)"
grant_project_role "$RUNTIME_SA" roles/aiplatform.user    # call Gemini on Vertex AI
grant_project_role "$RUNTIME_SA" roles/logging.logWriter  # write logs

echo "== 4. Build service account: $BUILD_SA"
create_sa "$BUILD_SA" "Fixture image builder (Cloud Build)"
grant_project_role "$BUILD_SA" roles/logging.logWriter    # build logs
# Push images to this one repository only.
gcloud artifacts repositories add-iam-policy-binding "$REPOSITORY" --location "$REGION" --project "$PROJECT_ID" \
  --member "serviceAccount:$BUILD_SA" --role roles/artifactregistry.writer >/dev/null

echo "== 5. Cloud Build source bucket: $BUILD_BUCKET"
if ! gcloud storage buckets describe "$BUILD_BUCKET" --project "$PROJECT_ID" >/dev/null 2>&1; then
  gcloud storage buckets create "$BUILD_BUCKET" --project "$PROJECT_ID" --location "$REGION" \
    --uniform-bucket-level-access
fi
# The builder only needs to read the source archives deploy.sh uploads.
gcloud storage buckets add-iam-policy-binding "$BUILD_BUCKET" \
  --member "serviceAccount:$BUILD_SA" --role roles/storage.objectViewer >/dev/null

echo "Done. Next: src/classifier/deploy.sh"
