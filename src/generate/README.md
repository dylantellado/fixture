# generate

Writes fictional scheduling threads for students and young people, **state first**: code picks
who writes what and when, and the true thread state after every email; Claude only writes the
text. So every label, `needs_response` and state is known by construction, and follows
[`docs/data/labeling_rules.md`](../../docs/data/labeling_rules.md) (v1.5).

Design: the "Generating threads from states" and "Making the dataset diverse" sections of the
Thread state proposal doc. State schema: v0.1 in the same doc.

## How it works

1. **Cards** (`cards/`): the mailbox owners (`users.yaml`: life context, time zone, dates, who
   they deal with, train or eval split), the people they schedule with (`counterparts.yaml`:
   title, domain, topics, writing styles, which thread shapes they take part in, how often an
   assistant is involved) and name pools.
2. **Sampler** (`sampler.py`, seeded): for each thread, picks a counterpart, a flow (a thread
   shape from `acts.FLOWS`), the people, the send times, and real meeting slots. Each slot is
   written in a sampled style (`times.py`): "Tue 11/17 at 3pm ET", "Wednesday afternoon",
   "17/11 at 15:00", "tomorrow at 10am", "Friday 2-4pm". It tracks the true state after each
   email.
3. **Answers** (`acts.py`): each email's act (ask, offer, accept, cancel, ...) maps to its label,
   `needs_response` and the rule ids, e.g. `still_on` → `none`, `true` (E13, NR6). A message the
   user sent is always `false` (NR1).
4. **Writer** (`writer.py`): one Claude call per thread (`claude-opus-5-5`, structured JSON
   output, server-side refusal fallback). The writer sees what each email does and the exact
   time phrases to use, never label names. Code rejects drafts that miss a phrase, add a clock
   time where none belongs, or leak a label name, and asks for a rewrite (up to 3 tries).
5. **Mess** (`mess.py`, seeded): signatures, "Sent from my iPhone", legal footers and quoted
   history are added in code and logged per message, so the writer's text stays clean.

## Outputs

`generate` writes `data/generated/` (DVC output; never in git):

| File | Contents |
|---|---|
| `threads.jsonl` | Threads in the `data/source/generated_threads.jsonl` format (Data contract) |
| `annotations.jsonl` | `needs_response`, rule and rationale per message (same format as data-v1) |
| `thread_states.jsonl` | Per thread: flow, counterpart, seed, card version, participants (`P0` is the user), and the true state after every message |
| `users.json` | The generated users, with their split |
| `generation_log.jsonl` | Per thread: prompt hash, writer model, tokens, attempts, and the mess added |

`assemble` combines `data/base/` (data-v1) and `data/generated/` into `data/source/`, adding
`splits.json` (`train`: data-v1 users and generated train users; `eval`: held-out generated users).

Claude writes are cached in `data/cache/generate/writes.jsonl` by the hash of the exact prompt,
so reruns and crashes never pay twice for the same thread.

## Run

From the repo root, through DVC (settings in `params.yaml`):

```sh
dvc repro generate   # needs ANTHROPIC_API_KEY
dvc repro            # generate -> assemble -> ingest -> preprocess
```

Directly, from `src/generate`:

```sh
uv run python main.py generate --dry-run --show 5        # scenarios and answers, no API calls
uv run python main.py generate --limit 4                 # a quick paid check: 4 threads
uv run python main.py generate                           # every user, 30 threads each
uv run python main.py assemble
uv run pytest
```

Cost: about 240 threads, one call each (plus rewrites), at `claude-opus-5-5` rates. The run logs
total writer tokens.

## Rules for changing it

- Changing a card, flow, seed or the writer prompt changes the data: make a new data version
  (`docs/data/versions.md`).
- A label or `needs_response` mapping in `acts.py` must cite the rule ids it follows. If the
  labeling rules change, update `acts.py` and `RULES_VERSION` in the same PR.
- `eval` users never feed tuning (see `experiments/classifier_tuning`).
