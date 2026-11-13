# Shared settings for the tuning job's Google Cloud scripts. Sourced, not run.
# Any value can be overridden from the environment.

PROJECT_ID="${PROJECT_ID:-fixture-ac215-96dhbm}"
REGION="${REGION:-us-east1}"                  # Vertex AI jobs, Cloud Build, Artifact Registry
REPOSITORY="${REPOSITORY:-fixture}"           # shared with the classifier (src/classifier/cloud)
IMAGE_BASE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/classifier-tuning"

# The job runs as JOB_SA: call Gemini, write logs, read the tuning inputs in the DVC
# bucket and read the W&B key. Cloud Build runs as the classifier's builder account.
JOB_SA="fixture-tuning@${PROJECT_ID}.iam.gserviceaccount.com"
BUILD_SA="fixture-builder@${PROJECT_ID}.iam.gserviceaccount.com"
BUILD_BUCKET="gs://${PROJECT_ID}_cloudbuild"

DVC_BUCKET="gs://fixture-ac215-96dhbm-dvc"
INPUTS_PREFIX="${DVC_BUCKET}/tuning-inputs"   # data copied here under the messages file's md5

WANDB_SECRET="wandb-api-key"
WANDB_BASE_URL="${WANDB_BASE_URL:-https://api.forge.coreweave.com}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-standard-4}" # the job waits on Gemini; no GPU needed
