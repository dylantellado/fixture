#!/usr/bin/env bash
# Make the Docker build folder for the Cloud Run image.
#
# Usage: cloud/build_context.sh OUT_DIR
#
# OUT_DIR gets exactly these files, all taken from the last commit (git HEAD), never
# from uncommitted edits:
#   - src/classifier: Dockerfile, .dockerignore, pyproject.toml, uv.lock,
#     .python-version and the service's .py files (not tests)
#   - docs/data/labeling_rules.md, saved as labeling_rules.md (the Dockerfile sets
#     RULES_PATH=/app/labeling_rules.md)
# Nothing else from the repo: no data/, no docs/data/training_conflicts.md.
set -euo pipefail

out="${1:?usage: cloud/build_context.sh OUT_DIR}"
repo_root="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
mkdir -p "$out"

# The service's code: every committed .py file in src/classifier except tests.
code_files=$(git -C "$repo_root" ls-tree --name-only HEAD src/classifier/ \
  | grep '\.py$' | grep -v -e '/test_' -e '/conftest\.py$')
git -C "$repo_root" archive HEAD \
  src/classifier/Dockerfile src/classifier/.dockerignore src/classifier/pyproject.toml \
  src/classifier/uv.lock src/classifier/.python-version $code_files \
  | tar -x -C "$out" --strip-components=2

# The exact rules file from the same commit.
git -C "$repo_root" show HEAD:docs/data/labeling_rules.md > "$out/labeling_rules.md"
