# Gemini baseline: gemini-3.8-flash on the training data

## Run

- Model: `gemini-3.8-flash` (served as `gemini-3.8-flash`), Vertex AI `fixture-ac215-96dhbm` / `global`, temperature 0, structured JSON output
- Labeling rules: v1.2 (`docs/data/labeling_rules.md`, without the "Not adopted" and "Change log" sections); annotations follow v1.2
- Git commit: `79b1d864cd67e95de54d53b8bed7fe30b22cbee4`
- Date: 2026-10-29 19:03 UTC
- Messages: 20 (--limit 20), users user_01
- Failures: 0 (left out of every score below)

## Labels

**Accuracy: 1.000** on 20 messages.

| label | precision | recall | f1 | support |
|---|---|---|---|---|
| new_request | 1.000 | 1.000 | 1.000 | 3.000 |
| proposed_times | 1.000 | 1.000 | 1.000 | 5.000 |
| acceptance | 1.000 | 1.000 | 1.000 | 6.000 |
| reschedule | 1.000 | 1.000 | 1.000 | 1.000 |
| assistant_handoff | 0.000 | 0.000 | 0.000 | 0.000 |
| none | 1.000 | 1.000 | 1.000 | 5.000 |

### Confusion matrix (rows: true label, columns: predicted)

| true \ pred | new_request | proposed_times | acceptance | reschedule | assistant_handoff | none |
|---|---|---|---|---|---|---|
| new_request | 3 | 0 | 0 | 0 | 0 | 0 |
| proposed_times | 0 | 5 | 0 | 0 | 0 | 0 |
| acceptance | 0 | 0 | 6 | 0 | 0 | 0 |
| reschedule | 0 | 0 | 0 | 1 | 0 | 0 |
| assistant_handoff | 0 | 0 | 0 | 0 | 0 | 0 |
| none | 0 | 0 | 0 | 0 | 0 | 5 |

### Scheduling vs `none`

- **Recall on the five scheduling labels combined: 1.000** (0 of 15 scheduling emails predicted `none`, the worst error)
- False alarms: 0 of 5 `none` emails predicted as a scheduling label
- Hard negatives: not scored. `data/source/annotations.jsonl` doesn't mark hard negatives (only the generation outlines in `docs/data/generation/` mention some in prose).

## needs_response

- Accuracy 1.000, precision 1.000, recall 1.000 (6 messages need a response)
- Replies missed (true, predicted false): 0; extra (false, predicted true): 0

## By user

| users | messages | failures | label_acc | sched_recall | sched_as_none | nr_acc |
|---|---|---|---|---|---|---|
| user_01 | 20.000 | 0.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| user_01–03 | 20.000 | 0.000 | 1.000 | 1.000 | 0.000 | 1.000 |
| all | 20.000 | 0.000 | 1.000 | 1.000 | 0.000 | 1.000 |

## Cost and latency

- Tokens: 71,237 input (0 of them served from Vertex's implicit cache), 1,055 output, 4,019 thinking
- Estimated cost: $0.07 at $0.75/1M input and $3.75/1M output+thinking (list price, no caching discount)
- Latency per call: median 3.42 s, p95 5.63 s (concurrency 4)

## Mistakes

All mistakes by kind (label mistakes first; a needs_response mistake is only counted when the label is right):

- none

### The 20 most informative

Spread over the kinds of error, worst first: scheduling missed, false alarms, wrong scheduling label, then needs_response.

| message_id | user | subject | true | predicted | needs_response true → pred | Gemini's reason |
|---|---|---|---|---|---|---|
