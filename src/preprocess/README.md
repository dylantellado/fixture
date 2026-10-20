# preprocess

Second step of the data pipeline. Turns ingest's threads into one clean,
anonymized record per message, in the `messages.jsonl` schema from the Data
contract (repo README). This is what `rag` indexes.

## Inputs and outputs

| | Path (inside `DATA_DIR`, `/data` in Docker) | |
|---|---|---|
| reads | `raw/threads.jsonl` | from `ingest` |
| reads | `source/users.json` | so the manifest's per-user counts list every user |
| writes | `processed/messages.jsonl` | one message per line |
| writes | `processed/manifest.json` | `created_at`, `git_commit`, counts (total, per user, threads, per label), sha256 of every input and output |

## What it does, per message

1. **`message_id`** = first 16 hex characters of `sha256("<user_id>|<thread_id>|<position>")`,
   where `position` is the message's index in its thread in `raw/threads.jsonl`.
   No message is ever dropped, so ids never shift and reruns give the same ids.
2. **Clean the body** (`cleaning.py`), in this order:
   - forwards: keep the forwarded text, shrink its header to `Forwarded message from <name>:`
   - quoted history: cut from the first `On ... wrote:`, Outlook `____` / `From: ... Sent:` block or `-----Original Message-----`; drop any `>` lines
   - footers: drop mobile lines (`Sent from my iPhone`), everything after a `--` line, and confidentiality / unsubscribe paragraphs
   - signatures: keep the sign-off and name (`Best,\nDana`), drop title and phone lines after them; drop a short last paragraph that starts with the sender's name
   - whitespace: trim lines, squash spaces, at most one blank line in a row
3. **Anonymize** (`anonymize.py`): email addresses → `EMAIL_###`, phone numbers →
   `PHONE_###`. There is **one map for all users**, numbered in sorted order, so the same
   address gets the same placeholder in every inbox and the numbering doesn't depend on
   read order. Phone numbers are normalized first, so `(617) 555-0142`, `617.555.0142` and
   `+1 617 555 0142` are one number. Display names are kept, because search by contact needs them.
4. **Timestamp** `Tue, 13 Oct 2026 09:12:00 -0400` → `2026-10-13T09:12:00-04:00` (sender's offset kept).
5. **Check before writing:** unique ids, contract fields are strings, `recipients` is a list,
   and no address or long number survived anonymization.

Any failure exits 1 and writes nothing, so `rag` never runs on bad data. `messages.jsonl`
is written first and `manifest.json` last, each through a temp file and a rename. If a
manifest exists, it describes a complete messages file.

**Known limits:** the cleaning rules fit the patterns in our corpus. Real email will
bring more (HTML, other languages' quote headers, signatures without a sign-off line).
Numbers with 10 to 13 digits are treated as phone numbers, so a long order or booking
number would be anonymized too, which errs on the safe side.

## Run it

```sh
# from the repo root; GIT_COMMIT is recorded in the manifest (the container has no git)
GIT_COMMIT=$(git rev-parse HEAD) docker compose up --build ingest preprocess

# locally, from src/preprocess (asks git for the commit itself)
uv run python main.py

uv run pytest   # includes checks on the real corpus when data/processed exists
```

## Files

- `main.py`: the job (flatten, ids, timestamps, checks, manifest, safe writes)
- `cleaning.py`: body cleaning rules
- `anonymize.py`: the global placeholder map
- `test_cleaning.py`, `test_anonymize.py`, `test_preprocess.py`: tests
