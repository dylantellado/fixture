#!/usr/bin/env bash
# Build the classifier image with Cloud Build and deploy it to Cloud Run. One command
# for every (re)deploy:
#
#   src/classifier/deploy.sh
#
# Before the first deploy, run cloud/setup.sh once (APIs, service accounts, registry),
# and afterwards cloud/monitoring.sh once (metrics, dashboard, uptime check).
#
# It deploys the last commit, not uncommitted edits, so every image is tagged with
# (and traceable to) a git commit. Docker doesn't need to run locally.
set -euo pipefail
cd "$(dirname "$0")"
source cloud/config.sh

# 1. Refuse to deploy uncommitted changes to the code or the rules.
if [ -n "$(git status --porcelain -- . ../../docs/data/labeling_rules.md)" ]; then
  echo "Uncommitted changes in src/classifier or docs/data/labeling_rules.md." >&2
  echo "Commit them first: deploy.sh builds from the last commit." >&2
  exit 1
fi
COMMIT="$(git rev-parse --short=12 HEAD)"
IMAGE="${IMAGE_BASE}:${COMMIT}"
RULES_SHA256="$(git show HEAD:docs/data/labeling_rules.md | shasum -a 256 | cut -d' ' -f1)"

# 2. Build and push the image, unless this commit was already built.
if gcloud artifacts docker images describe "$IMAGE" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "== Image for commit $COMMIT already exists, skipping the build"
else
  echo "== Building $IMAGE with Cloud Build"
  BUILD_DIR="$(mktemp -d)"
  trap 'rm -rf "$BUILD_DIR"' EXIT
  cloud/build_context.sh "$BUILD_DIR"   # the code + the exact rules file, from HEAD
  gcloud builds submit "$BUILD_DIR" \
    --project "$PROJECT_ID" --region "$REGION" \
    --config cloud/cloudbuild.yaml --substitutions "_IMAGE=$IMAGE" \
    --service-account "projects/$PROJECT_ID/serviceAccounts/$BUILD_SA" \
    --gcs-source-staging-dir "$BUILD_BUCKET/source"
fi

# 3. Deploy. Each setting:
#   --service-account          runs as fixture-classifier (Vertex AI user + log writer only)
#   --no-allow-unauthenticated callers need roles/run.invoker and an identity token
#   --min-instances 0          scale to zero when idle: no cost between requests
#   --max-instances 2          caps cost and Gemini load (2 x 20 = 40 emails at once)
#   --cpu 1 --memory 512Mi     the app uses ~150 MB; 1 vCPU is the minimum for concurrency > 1
#   --concurrency 20           requests per instance. Each mostly waits 2-15 s on Gemini,
#                              so one instance can serve the web app's 5 parallel calls and more
#   --timeout 150              Gemini worst case: 4 tries x 30 s timeout + ~7 s of waits
#   --cpu-throttling           CPU (and billing) only while handling requests
#   --cpu-boost                extra CPU during startup, for faster cold starts
#   --set-env-vars             model settings; replaces all env vars, so nothing stale remains
#   --labels                   which commit and rules file is running (also logged at startup)
echo "== Deploying $SERVICE ($REGION)"
gcloud run deploy "$SERVICE" \
  --project "$PROJECT_ID" --region "$REGION" --image "$IMAGE" \
  --service-account "$RUNTIME_SA" \
  --no-allow-unauthenticated \
  --min-instances 0 --max-instances 2 \
  --cpu 1 --memory 512Mi \
  --concurrency 20 \
  --timeout 150 \
  --cpu-throttling --cpu-boost \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=$GEMINI_LOCATION,GEMINI_MODEL=$GEMINI_MODEL,GEMINI_THINKING_BUDGET=$GEMINI_THINKING_BUDGET" \
  --labels "app=fixture,component=classifier,git-commit=$COMMIT,rules-sha256=${RULES_SHA256:0:12}"

# The stable URL (Cloud Run also serves an older-style *.a.run.app alias).
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format 'value(projectNumber)')"
URL="https://${SERVICE}-${PROJECT_NUMBER}.${REGION}.run.app"
echo
echo "Deployed commit $COMMIT (rules sha256 ${RULES_SHA256:0:12}...) to $URL"
echo "Check it:"
echo "  curl -H \"Authorization: Bearer \$(gcloud auth print-identity-token)\" $URL/health"
