#!/usr/bin/env bash
# Run the Vertex AI pipeline on the data version checked out here.
#
# Usage, from the repo root after `dvc pull` and experiments/classifier_tuning/cloud/setup.sh once:
#   src/pipeline/run_pipeline.sh [--harness harnesses/prod_v1.yaml] [--notes "..."] [--direct [--wait]]
#
# 1. Copies data/base and data/generated to gs://<dvc bucket>/pipeline-inputs/<version id>/,
#    where the id comes from their DVC hashes (skipped when already there).
# 2. Builds the two images (data steps, tuning) by content hash, unless they exist.
# 3. Compiles the pipeline with those images and saves it to gs://<bucket>/pipeline-templates/
#    (also as latest.json, which the trigger uses).
# 4. Writes <version id>/READY, which fires the trigger function (deploy_trigger.sh) to start
#    the run. With --direct, submits the run from here instead (no trigger needed).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(git -C "$here" rev-parse --show-toplevel)"
cloud="$repo/experiments/classifier_tuning/cloud"
source "$cloud/config.sh"
cd "$repo"

harness="harnesses/prod_v1.yaml"; notes="pipeline run"; wait=""; direct=""
while [ $# -gt 0 ]; do
  case "$1" in
    --harness) harness="$2"; shift 2 ;;
    --notes) notes="$2"; shift 2 ;;
    --wait) wait="--wait"; shift ;;
    --direct) direct=1; shift ;;  # submit from here instead of through the trigger
    *) echo "unknown option $1" >&2; exit 1 ;;
  esac
done

# 1. The data version: DVC's hashes of data/base and data/generated.
for d in data/base data/generated; do
  [ -d "$d" ] || { echo "$d is missing: run dvc pull first" >&2; exit 1; }
done
base_md5="$(grep -m1 'md5:' data/base.dvc | awk '{print $NF}' | cut -c1-12)"
gen_md5="$(uv run --directory src/pipeline python -c "
import yaml; lock = yaml.safe_load(open('$repo/dvc.lock'))
print(next(o['md5'] for o in lock['stages']['generate']['outs'] if o['path'] == 'data/generated')[:12])")"
inputs="$DVC_BUCKET/pipeline-inputs/${base_md5}-${gen_md5}"
if ! gcloud storage ls "$inputs/UPLOADED" >/dev/null 2>&1; then
  echo "== Uploading the data version to $inputs"
  gcloud storage cp --recursive --quiet data/base "$inputs/"
  gcloud storage cp --recursive --quiet data/generated "$inputs/"
  date -u +%FT%TZ | gcloud storage cp --quiet - "$inputs/UPLOADED"
fi

# 2. Images.
data_image="$("$cloud/build_image.sh" data | tail -1)"
tuning_image="$("$cloud/build_image.sh" tuning | tail -1)"

# 3. Compile, save, submit.
template="$(mktemp -d)/pipeline.json"
uv run --directory src/pipeline python pipeline.py compile --data-image "$data_image" \
  --tuning-image "$tuning_image" --out "$template"
name="${data_image##*:}-${tuning_image##*:}"
gcloud storage cp --quiet "$template" "$DVC_BUCKET/pipeline-templates/$name.json"
gcloud storage cp --quiet "$template" "$DVC_BUCKET/pipeline-templates/latest.json"
if [ -n "$direct" ]; then
  run_name="fixture-$(date -u +%Y%m%d-%H%M%S)"
  uv run --directory src/pipeline python pipeline.py submit --template "$template" --inputs "$inputs" \
    --run-name "$run_name" --harness "$harness" --notes "$notes" --region "$REGION" $wait
else
  # Writing READY (last, after the data and template) fires the trigger function,
  # which starts the run. Rewriting it starts another run on the same data.
  date -u +%FT%TZ | gcloud storage cp --quiet - "$inputs/READY"
  echo "== Wrote $inputs/READY: the trigger starts the pipeline (Vertex AI > Pipelines)"
fi
