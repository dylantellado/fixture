# Gemini baseline: gemini-3.8-flash on the training data

## Run

- Model: `gemini-3.8-flash` (served as `gemini-3.8-flash`), Vertex AI `fixture-ac215-96dhbm` / `global`, temperature 0, structured JSON output, thinking budget 128
- Labeling rules: v1.4 (`docs/data/labeling_rules.md`, without the "Not adopted" and "Change log" sections); annotations follow v1.4
- Rules text sent: sha256 `4c9445d441b62fe0e47ae57dad6df7428e2609ac9b3770538dfceb636b0b9a01`
- Git commit: `e9594f98525e3c194e257f89d3e502b84276d661`
- Date: 2026-10-30 02:04 UTC
- Messages: 377, users user_01, user_02, user_03, user_04
- Failures: 0 (left out of every score below)

## Labels

**Accuracy: 0.989** on 377 messages.

| label | precision | recall | f1 | support |
|---|---|---|---|---|
| new_request | 1.000 | 0.944 | 0.971 | 54 |
| proposed_times | 1.000 | 0.987 | 0.994 | 79 |
| acceptance | 1.000 | 1.000 | 1.000 | 105 |
| reschedule | 0.976 | 1.000 | 0.988 | 41 |
| assistant_handoff | 0.667 | 1.000 | 0.800 | 6 |
| none | 1.000 | 1.000 | 1.000 | 92 |

### Confusion matrix (rows: true label, columns: predicted)

| true \ pred | new_request | proposed_times | acceptance | reschedule | assistant_handoff | none |
|---|---|---|---|---|---|---|
| new_request | 51 | 0 | 0 | 0 | 3 | 0 |
| proposed_times | 0 | 78 | 0 | 1 | 0 | 0 |
| acceptance | 0 | 0 | 105 | 0 | 0 | 0 |
| reschedule | 0 | 0 | 0 | 41 | 0 | 0 |
| assistant_handoff | 0 | 0 | 0 | 0 | 6 | 0 |
| none | 0 | 0 | 0 | 0 | 0 | 92 |

### Scheduling vs `none`

- **Recall on the five scheduling labels combined: 1.000** (0 of 285 scheduling emails predicted `none`, the worst error)
- False alarms: 0 of 92 `none` emails predicted as a scheduling label
- Hard negatives: not scored. `data/source/annotations.jsonl` doesn't mark hard negatives (only the generation outlines in `docs/data/generation/` mention some in prose).

## needs_response

- Accuracy 1.000, precision 1.000, recall 1.000 (109 messages need a response)
- Replies missed (true, predicted false): 0; extra (false, predicted true): 0

## By user

| users | messages | failures | label_acc | sched_recall | sched_as_none | nr_acc |
|---|---|---|---|---|---|---|
| user_01 | 100 | 0 | 0.990 | 1.000 | 0 | 1.000 |
| user_02 | 97 | 0 | 0.969 | 1.000 | 0 | 1.000 |
| user_03 | 90 | 0 | 1.000 | 1.000 | 0 | 1.000 |
| user_04 | 90 | 0 | 1.000 | 1.000 | 0 | 1.000 |
| user_01–03 | 287 | 0 | 0.986 | 1.000 | 0 | 1.000 |
| all | 377 | 0 | 0.989 | 1.000 | 0 | 1.000 |

## Cost and latency

- Tokens: 1,358,360 input (0 of them served from Vertex's implicit cache), 22,631 output, 3,033 thinking
- Estimated cost: $1.12 at $0.75/1M input and $3.75/1M output+thinking (list price, no caching discount)
- Latency per call: median 2.74 s, p95 42.36 s (concurrency 4)

## Mistakes

All mistakes by kind (label mistakes first; a needs_response mistake is only counted when the label is right):

- new_request → assistant_handoff: 3
- proposed_times → reschedule: 1

### The 20 most informative

Spread over the kinds of error, worst first: scheduling missed, false alarms, wrong scheduling label, then needs_response.

| message_id | user | subject | true | predicted | needs_response true → pred | Gemini's reason |
|---|---|---|---|---|---|---|
| 47af86117df33131 | user_01 | Larkmoor Capital: Superday invitation | new_request | assistant_handoff | False → False | Jordan hands off scheduling to Tess under D5/T2, and no reply is needed from Priya since Tess will reach out directly (NR1). |
| 7ae0f9aeb1b22234 | user_02 | Pinecrest Labs final round | new_request | assistant_handoff | False → False | Tom hands scheduling of the final round over to Gwen, making this an assistant handoff per D5 and PR3, with needs_response false per NR1 as Gwen will initiate contact. |
| 49ec03bc60f62177 | user_02 | Larkmoor Capital: final round | new_request | assistant_handoff | False → False | Jordan hands off scheduling the final round interviews to Tess (D5, T2), and Marcus does not need to reply since Tess is explicitly designated to reach out (NR1). |
| e3f8c97e38dafbee | user_02 | Monday 10/19 | proposed_times | reschedule | True → True | The target message cancels/reschedules an existing recurring meeting occurrence to October 26 at 10:00 as a directive move under D4 and NR9. |
