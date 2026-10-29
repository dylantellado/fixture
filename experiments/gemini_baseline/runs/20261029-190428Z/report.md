# Gemini baseline: gemini-3.8-flash on the training data

## Run

- Model: `gemini-3.8-flash` (served as `gemini-3.8-flash`), Vertex AI `fixture-ac215-96dhbm` / `global`, temperature 0, structured JSON output
- Labeling rules: v1.2 (`docs/data/labeling_rules.md`, without the "Not adopted" and "Change log" sections); annotations follow v1.2
- Git commit: `79b1d864cd67e95de54d53b8bed7fe30b22cbee4`
- Date: 2026-10-29 19:04 UTC
- Messages: 377, users user_01, user_02, user_03, user_04
- Failures: 0 (left out of every score below)

## Labels

**Accuracy: 0.992** on 377 messages.

| label | precision | recall | f1 | support |
|---|---|---|---|---|
| new_request | 1.000 | 1.000 | 1.000 | 51 |
| proposed_times | 1.000 | 0.987 | 0.994 | 79 |
| acceptance | 1.000 | 0.990 | 0.995 | 101 |
| reschedule | 1.000 | 0.976 | 0.988 | 41 |
| assistant_handoff | 0.818 | 1.000 | 0.900 | 9 |
| none | 0.990 | 1.000 | 0.995 | 96 |

### Confusion matrix (rows: true label, columns: predicted)

| true \ pred | new_request | proposed_times | acceptance | reschedule | assistant_handoff | none |
|---|---|---|---|---|---|---|
| new_request | 51 | 0 | 0 | 0 | 0 | 0 |
| proposed_times | 0 | 78 | 0 | 0 | 1 | 0 |
| acceptance | 0 | 0 | 100 | 0 | 1 | 0 |
| reschedule | 0 | 0 | 0 | 40 | 0 | 1 |
| assistant_handoff | 0 | 0 | 0 | 0 | 9 | 0 |
| none | 0 | 0 | 0 | 0 | 0 | 96 |

### Scheduling vs `none`

- **Recall on the five scheduling labels combined: 0.996** (1 of 281 scheduling emails predicted `none`, the worst error)
- False alarms: 0 of 96 `none` emails predicted as a scheduling label
- Hard negatives: not scored. `data/source/annotations.jsonl` doesn't mark hard negatives (only the generation outlines in `docs/data/generation/` mention some in prose).

## needs_response

- Accuracy 1.000, precision 1.000, recall 1.000 (109 messages need a response)
- Replies missed (true, predicted false): 0; extra (false, predicted true): 0

## By user

| users | messages | failures | label_acc | sched_recall | sched_as_none | nr_acc |
|---|---|---|---|---|---|---|
| user_01 | 100 | 0 | 0.990 | 0.986 | 1 | 1.000 |
| user_02 | 97 | 0 | 1.000 | 1.000 | 0 | 1.000 |
| user_03 | 90 | 0 | 0.978 | 1.000 | 0 | 1.000 |
| user_04 | 90 | 0 | 1.000 | 1.000 | 0 | 1.000 |
| user_01–03 | 287 | 0 | 0.990 | 0.995 | 1 | 1.000 |
| all | 377 | 0 | 0.992 | 0.996 | 1 | 1.000 |

## Cost and latency

- Tokens: 1,346,296 input (0 of them served from Vertex's implicit cache), 20,102 output, 124,055 thinking
- Estimated cost: $1.55 at $0.75/1M input and $3.75/1M output+thinking (list price, no caching discount)
- Latency per call: median 3.51 s, p95 18.42 s (concurrency 4)

## Mistakes

All mistakes by kind (label mistakes first; a needs_response mistake is only counted when the label is right):

- reschedule → none (scheduling missed): 1
- proposed_times → assistant_handoff: 1
- acceptance → assistant_handoff: 1

### The 20 most informative

Spread over the kinds of error, worst first: scheduling missed, false alarms, wrong scheduling label, then needs_response.

| message_id | user | subject | true | predicted | needs_response true → pred | Gemini's reason |
|---|---|---|---|---|---|---|
| dedb6df0524a507a | user_01 | STAT 142: office hours this week | reschedule | none | False → False | This is a group announcement about office hours sent to a class mailing list, which is classified as none under E3 and requires no response under NR1. |
| 166482ab09374bcc | user_03 | Brightwater final round: Chicago | acceptance | assistant_handoff | False → False | The email introduces a recruiting coordinator who will handle the final round schedule and logistics, making it an assistant handoff that requires no response from the user under D5, T2, and NR1. |
| 76885a71c68ac079 | user_03 | Recurring meetings with Dr. Achebe | proposed_times | assistant_handoff | True → True | This is the first notice that scheduling is being handled by Dr. Achebe's assistant, which takes priority over proposed times under D5, T2, and PR, and requires a response under NR1 to confirm the arrangement. |
