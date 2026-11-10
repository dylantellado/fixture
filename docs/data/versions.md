# Data versions

Every dataset Fixture trains, tunes or scores on is versioned with [DVC](https://dvc.org).
Git holds the code and small pointer files; the data itself lives in a private Cloud Storage
bucket. A git commit therefore pins the exact data, the code that made it, and the hash of every
file in between.

## How it fits together

| Piece | Where | What it holds |
|---|---|---|
| `data/source.dvc` | git | Hash of the `data/source/` folder: the pipeline's inputs (users, threads, annotations) |
| `dvc.yaml` | git | The pipeline: `ingest` → `preprocess`, with each stage's command, inputs (code and data) and outputs |
| `dvc.lock` | git | The md5 of every input and output of the last run. Committed with the code, it records which code made which data |
| `.dvc/config` | git | The remote: `gs://fixture-ac215-96dhbm-dvc/dvcstore` |
| The files themselves | the bucket, and `.dvc/cache/` locally | Stored by hash, so nothing is ever overwritten in place |

The bucket (project `fixture-ac215-96dhbm`, `us-east1`) is private, with object versioning on, so
even a deleted object can be recovered. `data/eval/` stays in git, frozen by tag (see
[`data/eval/v1/README.md`](../../data/eval/v1/README.md)).

## Setup (once)

```sh
uv tool install "dvc[gs]==3.67.1"     # DVC with Google Cloud Storage support
gcloud auth application-default login # DVC uses these credentials, like Vertex AI
dvc pull                              # from the repo root: fetches data/source, data/raw, data/processed
```

Access: anyone with a role on the project (owners, editors) can already read the bucket. To give
someone else read-only access (this includes any real email stored here, see rule 6):

```sh
gcloud storage buckets add-iam-policy-binding gs://fixture-ac215-96dhbm-dvc \
  --member=user:THEIR_EMAIL --role=roles/storage.objectViewer
```

## Everyday commands (repo root)

```sh
dvc pull        # get the data for the commit you're on (after clone, checkout or pull)
dvc status      # has any input, code or output changed since dvc.lock?
dvc repro       # rerun only the stages whose inputs changed, then update dvc.lock
dvc push        # upload new data to the bucket (do this before pushing the git commit)
```

`docker compose up` still runs `ingest` and `preprocess` itself and writes the same files. It
needs `data/source/`, so run `dvc pull` first. `dvc repro` is the way to produce data you mean to
release, because only it updates `dvc.lock`.

## Rules

1. **Data never changes without a commit.** Change the inputs or code, run `dvc repro`, then
   commit `dvc.lock` (and `data/source.dvc` if the inputs changed) with the code in one commit.
2. **Push data before code.** `dvc push`, then `git push`, so nobody pulls a commit whose data
   isn't in the bucket.
3. **Releases are tags and are never moved.** A release is a git tag `data-vN` on `main` plus a
   row in the table below. A fix is a new version, never an edited old one.
4. **Eval sets are separate and frozen.** They stay in git under `data/eval/`, frozen by their
   own tags, and nothing is tuned on them. A generated eval set gets its own `eval-*` version.
5. **Seeds and settings are inputs too.** When the generator exists it becomes a `generate`
   stage in `dvc.yaml` that writes `data/source/`, with its seed range, card-file version and
   writer model in `params.yaml`. Then `data/source.dvc` is removed, since the stage records it.
6. **Real email goes in the bucket only, never git.** Will and Dylan agreed (2026-11-09) that
   their own inbox emails may be versioned here, e.g. as a real eval set. Those emails also hold
   other people's messages, so: keep real data in its own folder and version (`data/real/`,
   `real-vN` tags), separate from generated data; never commit it to git or `samples/`; never
   make the bucket public. Read access is bucket-wide, so granting a TF `objectViewer` also shows
   them our real emails. Share a generated-only copy instead, or ask first.

## Making a release

1. On a feature branch: change the inputs or code, `dvc repro`, check `dvc status` says up to date.
2. Check the counts in `data/processed/manifest.json` and write them in a new row below.
3. `dvc push`, commit, open a PR. Note any change to file shapes in the README's Data contract.
4. After the merge: `git tag data-vN <merge commit>` and `git push origin data-vN`.

To get an old version: `git checkout data-vN && dvc pull`.

## Versions

| Version | Date | What | Messages | Threads | `data/source` md5 |
|---|---|---|---|---|---|
| data-v1 | 2026-10-19 (DVC since 2026-11-09) | 4 fictional users, scheduling emails generated from `docs/data/generation/`; labeling rules v1.5 | 377 | 160 | `acc2a878388b4202524e4309e21909a1` |

data-v1 labels: acceptance 105, none 92, proposed_times 78, new_request 51, reschedule 41,
assistant_handoff 10; `needs_response` 109 true, 268 false.
