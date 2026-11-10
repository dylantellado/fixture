#!/usr/bin/env bash
# Run one tuning run as a Vertex AI custom job (serverless: no machine to manage).
#
# Usage, from the repo root after `dvc pull` (or `dvc repro`) and cloud/setup.sh once:
#   experiments/classifier_tuning/cloud/run_vertex_job.sh [main.py args...]
#   e.g. experiments/classifier_tuning/cloud/run_vertex_job.sh --harness harnesses/prod_v1.yaml --notes "baseline"
#
# What it does:
#   1. Copies the data files tuning reads to gs://<dvc bucket>/tuning-inputs/<md5 of messages.jsonl>/
#      (skipped if already there), so the job reads an exact, named data version.
#   2. Builds the image (code + harnesses + labeling_rules.md) with Cloud Build, tagged by
#      the hash of its contents, unless that exact image already exists.
#   3. Starts the custom job as fixture-tuning, with the W&B key from Secret Manager, and
#      streams its logs. Results go to W&B like a local run (job_type "tune").
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/config.sh"
repo="$(git -C "$here" rev-parse --show-toplevel)"
cd "$repo"

# 1. Inputs, named by the md5 DVC also uses for messages.jsonl.
files=(processed/messages.jsonl source/annotations.jsonl source/users.json source/splits.json source/thread_states.jsonl)
for f in "${files[@]}"; do
  [ -f "data/$f" ] || { echo "data/$f is missing: run dvc pull (or dvc repro) first" >&2; exit 1; }
done
md5="$(md5 -q data/processed/messages.jsonl 2>/dev/null || md5sum data/processed/messages.jsonl | cut -d' ' -f1)"
inputs="$INPUTS_PREFIX/$md5"
if ! gcloud storage ls "$inputs/source/thread_states.jsonl" >/dev/null 2>&1; then
  echo "== Copying inputs to $inputs"
  for f in "${files[@]}"; do gcloud storage cp --quiet "data/$f" "$inputs/$f"; done
fi

# 2. Image, built from the working tree (the run records the git commit, marked -dirty if
#    there are uncommitted changes).
image="$("$here/build_image.sh" tuning | tail -1)"

# 3. The job.
commit="$(git rev-parse HEAD)$([ -n "$(git status --porcelain)" ] && echo -dirty || true)"
job_config="$(mktemp)"
trap 'rm -f "$job_config"' EXIT
{
  echo "workerPoolSpecs:"
  echo "  - machineSpec: {machineType: $MACHINE_TYPE}"
  echo "    replicaCount: 1"
  echo "    containerSpec:"
  echo "      imageUri: $image"
  echo "      args:"
  echo "        - --data-root"
  echo "        - $inputs"
  for arg in "$@"; do printf '        - %s\n' "$(printf '%s' "$arg" | sed 's/"/\\"/g; s/.*/"&"/')"; done
  echo "      env:"
  echo "        - {name: WANDB_API_KEY_SECRET, value: projects/$PROJECT_ID/secrets/$WANDB_SECRET/versions/latest}"
  echo "        - {name: WANDB_BASE_URL, value: \"$WANDB_BASE_URL\"}"
  echo "        - {name: GOOGLE_CLOUD_PROJECT, value: $PROJECT_ID}"
  echo "        - {name: GIT_COMMIT, value: $commit}"
  echo "serviceAccount: $JOB_SA"
} > "$job_config"

name="classifier-tuning-$(date -u +%Y%m%d-%H%M%S)"
echo "== Starting Vertex AI custom job $name"
job="$(gcloud ai custom-jobs create --project "$PROJECT_ID" --region "$REGION" \
  --display-name "$name" --config "$job_config" --format 'value(name)')"
echo "Job: $job"
echo "Console: https://console.cloud.google.com/vertex-ai/training/custom-jobs?project=$PROJECT_ID"
gcloud ai custom-jobs stream-logs "$job" --region "$REGION" --project "$PROJECT_ID" || true
gcloud ai custom-jobs describe "$job" --region "$REGION" --project "$PROJECT_ID" --format 'value(state)'
