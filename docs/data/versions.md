# Data versions

Every dataset Fixture trains, tunes or scores on is versioned with [DVC](https://dvc.org).
Git holds the code and small pointer files; the data itself lives in a private Cloud Storage
bucket. A git commit therefore pins the exact data, the code that made it, and the hash of every
file in between.

## How it fits together

| Piece | Where | What it holds |
|---|---|---|
| `data/source.dvc` | git | Hash of the `data/source/` folder: the pipeline's inputs (users, threads, annotations) |
| `dvc.yaml` | git | The pipeline: `ingest` → `preprocess`, with each stage's command, inputs (code folders and data) and outputs |
| `dvc.lock` | git | The md5 of every input and output of the last run. Committed with the code, it records which code made which data |
| `.dvc/config` | git | The remote: `gs://fixture-ac215-96dhbm-dvc/dvcstore` |
| `.dvcignore` | git | What DVC skips when hashing folders (OS clutter, caches, tests, READMEs) |
| The files themselves | the bucket, and `.dvc/cache/` locally | Stored by hash, so nothing is overwritten in place |

The bucket (project `fixture-ac215-96dhbm`, `us-east1`) is private, with object versioning on: a
deleted or overwritten object can be recovered for 30 days, then the lifecycle rule in
[`bucket_lifecycle.json`](bucket_lifecycle.json) deletes it for good.

### What's where in `data/`

The same list is in the README and `CLAUDE.md`:

- **Tracked by DVC** (get them with `dvc pull`; don't edit them by hand, since `dvc pull` and
  `dvc checkout` overwrite them): `data/source/`, `data/raw/threads.jsonl`,
  `data/processed/messages.jsonl` and `data/processed/manifest.json`.
- **In git:** `data/eval/` (frozen by its tags, see [`data/eval/v1/README.md`](../../data/eval/v1/README.md))
  and the `data/*.dvc` pointer files.
- **Only local:** `data/fixture.db` (the web app's encrypted logins), `data/processed/run.json`
  (when and from which commit preprocess last ran), and the eval `work/` and `processed/` folders.

## Setup (once)

```sh
uv tool install "dvc[gs]==3.67.1"     # DVC with Google Cloud Storage support
gcloud auth application-default login # DVC uses these credentials, like Vertex AI
dvc pull                              # from the repo root: fetches data/source, data/raw, data/processed
```

Access: only project owners and editors can read the bucket, which includes any service account
with the Editor role. Project viewers can't (their default bindings were removed). To give one
more person read-only access, which includes any real email stored here (see rule 6):

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

## Which code made this data

`dvc.lock` is the authoritative link between code and data. It is committed together with the
outputs and records the md5 of every code dependency (each stage depends on its whole service
folder), so a data version's code is the commit whose `dvc.lock` has its hashes:

- for a release, its `data-vN` tag;
- otherwise `git log -S <md5 of messages.jsonl> -- dvc.lock`.

`data/processed/manifest.json` holds only what the inputs and code determine (counts and
sha256), so rerunning on the same inputs writes a byte-identical file and `dvc status` stays
clean. The time and the commit a run started from (`run_from_commit`, plus `dirty` when there
were uncommitted changes) go to the untracked `data/processed/run.json`: a hint for people, not
the record.

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
   other people's messages, so:
   - keep real data only under `data/real/`, in its own versions (`real-vN` tags), separate from
     generated data;
   - anonymize it with preprocess before upload where possible;
   - never commit it to git, tests, `samples/` or commit messages, and never log it;
   - the bucket stays private: only project owners and editors can read it, and granting anyone
     `objectViewer` shows them our real emails too, so share a generated-only copy instead, or
     ask first. `CLAUDE.md` states the same rule.

## Making a release

1. On a feature branch: change the inputs or code, `dvc repro`, check `dvc status` says up to
   date. Then run `uv run pytest -rs` in `src/ingest` and `src/preprocess` and confirm nothing
   skips: their data checks run only when the data is present.
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
