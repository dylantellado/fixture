#!/usr/bin/env bash
# Build an image with Cloud Build, tagged by the hash of its contents, unless it exists.
# Prints the image URI on the last line of stdout. Used by run_vertex_job.sh and
# src/pipeline/run_pipeline.sh.
#
#   build_image.sh tuning   experiments/classifier_tuning code + harnesses + labeling_rules.md
#   build_image.sh data     src/generate, src/ingest, src/preprocess (the pipeline's data steps)
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
source "$here/config.sh"
repo="$(git -C "$here" rev-parse --show-toplevel)"
cd "$repo"
kind="${1:?usage: build_image.sh tuning|data}"

context="$(mktemp -d)"
trap 'rm -rf "$context"' EXIT
case "$kind" in
  tuning)
    mkdir -p "$context/experiments/classifier_tuning/harnesses" "$context/docs/data"
    cp experiments/classifier_tuning/{Dockerfile,pyproject.toml,uv.lock,.python-version,main.py,harness.py,data.py,scoring.py} \
      "$context/experiments/classifier_tuning/"
    cp experiments/classifier_tuning/harnesses/*.yaml "$context/experiments/classifier_tuning/harnesses/"
    cp docs/data/labeling_rules.md "$context/docs/data/"
    dockerfile="experiments/classifier_tuning/Dockerfile"
    image_name="classifier-tuning"
    ;;
  data)
    for s in generate ingest preprocess; do
      mkdir -p "$context/src/$s"
      cp src/$s/{pyproject.toml,uv.lock,.python-version} "$context/src/$s/"
      find src/$s -maxdepth 1 -name '*.py' ! -name 'test_*' ! -name 'conftest.py' -exec cp {} "$context/src/$s/" \;
    done
    cp -R src/generate/cards "$context/src/generate/"
    cp src/pipeline/Dockerfile.data "$context/Dockerfile"
    dockerfile="Dockerfile"
    image_name="fixture-data"
    ;;
  *) echo "unknown image kind: $kind" >&2; exit 1 ;;
esac

tag="$(cd "$context" && find . -type f | sort | xargs shasum -a 256 | shasum -a 256 | cut -c1-16)"
image="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPOSITORY}/${image_name}:${tag}"
if gcloud artifacts docker images describe "$image" --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "== Image $image already exists" >&2
else
  echo "== Building $image" >&2
  gcloud builds submit "$context" --project "$PROJECT_ID" --region "$REGION" \
    --config "$here/cloudbuild.yaml" --substitutions "_IMAGE=$image,_DOCKERFILE=$dockerfile" \
    --service-account "projects/$PROJECT_ID/serviceAccounts/$BUILD_SA" \
    --gcs-source-staging-dir "$BUILD_BUCKET/source" >&2
fi
echo "$image"
