# Eval set v1.1: eval-v1 under labeling rules v1.5

**Never tune on this set.** The same rules as eval-v1 apply (see [`../v1/README.md`](../v1/README.md)):
don't use it for prompt tuning, few-shot examples, picking a model or threshold, or training.

eval-v1.1 is eval-v1 with its answers brought up to
[`docs/data/labeling_rules.md`](../../../docs/data/labeling_rules.md) **v1.5**. eval-v1 stays
frozen at tag `eval-v1` and in `data/eval/v1/`, unchanged. The threads, users and every other
field are the same as v1, so everything in [`../v1/README.md`](../v1/README.md) about how the set
was made, who is in it and what it measures still holds. Only the answers listed below differ.

## Files

Copied from `data/eval/v1/`, with one change applied by `build.py apply-changes`:

| File | What |
|---|---|
| `threads.jsonl`, `annotations.jsonl` | As in v1, with the change below. Every annotation has `rules_version` `1.5`. |
| `users.json` | Same as v1. |
| `changes_rules_v1.0.json` to `changes_rules_v1.2.json` | v1's history, unchanged. |
| `changes_rules_v1.4.json` | The change made for rules v1.4. It still holds under v1.5, which changed no further answers (v1.3 changed no rules). |
| `build.py`, `check.py` | Same as v1, pointed at this folder. |

## Changes for labeling rules v1.4 and v1.5

v1.4 added E18 (recurring sessions), E19 (dividing tasks), E20 (the other person's first reply
confirming a time the user chose is `acceptance`) and NR10 (`needs_response` for
introductions), and reworded E14 and T2. v1.5 changed T2 again: the first message **in a
thread** that tells the user scheduling goes through someone else is `assistant_handoff`, judged
without looking at other threads. A first notice with a higher-ranking label (e.g. a
`reschedule`) still counts as the notice.

For both versions I checked every message these rules could reach, reading only thread text,
labels and `needs_response`, and no model output:
- every `assistant_handoff`, every earlier mention of the person taking over, and every message
  that says in words that scheduling goes through someone else (T2);
- every reply after a user's acceptance (E20, E14);
- every cancelled or moved recurring session (E18);
- every message that divides work (E19);
- every introduction (NR10).

**1 change** (made for v1.4; v1.5 keeps it and changes nothing else):

| message_id | Message | Field | Old → new | Rule |
|---|---|---|---|---|
| `400dac954386c1ba` | eval_03/t029/2 | label | `assistant_handoff` → `none` | T2 |

Graham's message `eval_03/t029/1`, earlier in the same thread, already told Noor that
Philippa Rowntree would come back with alternatives. It is labeled `reschedule`, which outranks
a handoff under PR, but it still counts as the thread's handoff notice. So Philippa's own
message is a later message in that thread, labeled by what it does: it says she will come back
with options, with no times and no ask. `needs_response` stays `false`.

Checked and unchanged:
- **E20:** after a user picks from several times, the replies are a bare "Thank you!" (`eval_03/t025/3`), "Noted, thank you" (`eval_01/t009/2`) or logistics only (`eval_01/t006/3`, `eval_01/t032/2`). None affirms the time.
- **T2:** the other 29 handoffs are each the first notice in their thread for their person, including the two different schedulers in `eval_03/t008`. Every assistant message that states the routing in words is either such a notice or a later message after one (e.g. `eval_01/t018/2`, `eval_03/t025/1`).
- **E18:** every recurring-session move or cancellation is already `reschedule`.
- **E19:** no message dividing work has a scheduling label.
- **NR10:** each introduction asks the other person to reach out and is already `false`.

## Counts

| | new_request | proposed_times | acceptance | reschedule | assistant_handoff | none | Total |
|---|---|---|---|---|---|---|---|
| v1 | 38 | 42 | 36 | 35 | 30 | 117 | 298 |
| **v1.1** | 38 | 42 | 36 | 35 | **29** | **118** | 298 |

`needs_response`: 68 `true`, 230 `false`, the same as v1. Hard negatives are 83 of 118 `none`
(70%).

## Checks

- `src/ingest/validate.py` (contract checks): 0 errors, 0 warnings.
- `ingest` and `preprocess` on a copy (below): all 140 threads and 298 messages kept, no empty
  body.
- `check.py final`: **1 error. `assistant_handoff` has 29 messages, below the 30 the set
  requires** (`MIN_PER_LABEL`). Everything else passes, including the 70% hard-negative share
  (exactly at the limit). The limit was left as it is. Raising the count needs new eval
  messages, or a decision to accept 29 for v1.1.

To rerun the pipeline without touching `data/raw/` or `data/processed/`:

```sh
EVAL_RUN=$(mktemp -d) && mkdir -p "$EVAL_RUN/source"
cp data/eval/v1.1/users.json "$EVAL_RUN/source/users.json"
cp data/eval/v1.1/threads.jsonl "$EVAL_RUN/source/generated_threads.jsonl"
(cd src/ingest && DATA_DIR="$EVAL_RUN" uv run python main.py)
(cd src/preprocess && DATA_DIR="$EVAL_RUN" uv run python main.py)
mkdir -p data/eval/v1.1/processed && cp "$EVAL_RUN"/processed/* data/eval/v1.1/processed/
python3 data/eval/v1.1/check.py final
```
