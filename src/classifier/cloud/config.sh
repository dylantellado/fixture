# Shared settings for the classifier's Google Cloud scripts (setup.sh, monitoring.sh,
# ../deploy.sh). Sourced by them, not run on its own. Any value can be overridden
# from the environment, e.g. REGION=us-central1 ../deploy.sh

PROJECT_ID="${PROJECT_ID:-fixture-ac215-96dhbm}"
# Region for Cloud Run, Cloud Build and Artifact Registry. Gemini itself is called on
# the "global" Vertex AI endpoint (GEMINI_LOCATION), which is separate.
REGION="${REGION:-us-east1}"
SERVICE="${SERVICE:-fixture-classifier}"     # Cloud Run service name
REPOSITORY="${REPOSITORY:-fixture}"          # Artifact Registry Docker repository
IMAGE_BASE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/classifier"

# The service runs as RUNTIME_SA (Vertex AI user + log writer only), and Cloud Build
# runs as BUILD_SA (push to the registry, read the uploaded source, write build logs).
# Neither is the default compute service account.
RUNTIME_SA="fixture-classifier@${PROJECT_ID}.iam.gserviceaccount.com"
BUILD_SA="fixture-builder@${PROJECT_ID}.iam.gserviceaccount.com"
# Cloud Build uploads the source here before building.
BUILD_BUCKET="gs://${PROJECT_ID}_cloudbuild"

# Model settings, passed to the service as environment variables.
GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.8-flash}"
GEMINI_LOCATION="${GEMINI_LOCATION:-global}"   # us-central1 returned 404 for Gemini 3.x Flash
GEMINI_THINKING_BUDGET="${GEMINI_THINKING_BUDGET:-128}"
