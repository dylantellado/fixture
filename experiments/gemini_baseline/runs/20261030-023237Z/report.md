# Gemini baseline: gemini-3.8-flash on the training data

## Run

- Model: `gemini-3.8-flash` (served as `gemini-3.8-flash`), Vertex AI `fixture-ac215-96dhbm` / `global`, temperature 0, structured JSON output, thinking budget 128
- Labeling rules: v1.5 (`docs/data/labeling_rules.md`, without the "Not adopted" and "Change log" sections); annotations follow v1.5
- Rules text sent: sha256 `ba009467a9ecd38bf0442622fd94f7d24bd550a49b40cbc82c256831585163bb`
- Git commit: `d48136889bbb49643a217bf09eea2662ea96e68a`
- Date: 2026-10-30 02:32 UTC
- Messages: 377, users user_01, user_02, user_03, user_04
- Failures: 0 (left out of every score below)

## Labels

**Accuracy: 0.995** on 377 messages.

| label | precision | recall | f1 | support |
|---|---|---|---|---|
| new_request | 1.000 | 0.980 | 0.990 | 51 |
| proposed_times | 1.000 | 0.987 | 0.994 | 78 |
| acceptance | 1.000 | 1.000 | 1.000 | 105 |
| reschedule | 0.976 | 1.000 | 0.988 | 41 |
| assistant_handoff | 0.909 | 1.000 | 0.952 | 10 |
| none | 1.000 | 1.000 | 1.000 | 92 |

### Confusion matrix (rows: true label, columns: predicted)

| true \ pred | new_request | proposed_times | acceptance | reschedule | assistant_handoff | none |
|---|---|---|---|---|---|---|
| new_request | 50 | 0 | 0 | 0 | 1 | 0 |
| proposed_times | 0 | 77 | 0 | 1 | 0 | 0 |
| acceptance | 0 | 0 | 105 | 0 | 0 | 0 |
| reschedule | 0 | 0 | 0 | 41 | 0 | 0 |
| assistant_handoff | 0 | 0 | 0 | 0 | 10 | 0 |
| none | 0 | 0 | 0 | 0 | 0 | 92 |

### Scheduling vs `none`

- **Recall on the five scheduling labels combined: 1.000** (0 of 285 scheduling emails predicted `none`, the worst error)
- False alarms: 0 of 92 `none` emails predicted as a scheduling label
- Hard negatives: not scored. `data/source/annotations.jsonl` doesn't mark hard negatives (only the generation outlines in `docs/data/generation/` mention some in prose).

## needs_response

- Accuracy 0.997, precision 0.991, recall 1.000 (109 messages need a response)
- Replies missed (true, predicted false): 0; extra (false, predicted true): 1

## By user

| users | messages | failures | label_acc | sched_recall | sched_as_none | nr_acc |
|---|---|---|---|---|---|---|
| user_01 | 100 | 0 | 1.000 | 1.000 | 0 | 1.000 |
| user_02 | 97 | 0 | 0.990 | 1.000 | 0 | 0.990 |
| user_03 | 90 | 0 | 1.000 | 1.000 | 0 | 1.000 |
| user_04 | 90 | 0 | 0.989 | 1.000 | 0 | 1.000 |
| user_01–03 | 287 | 0 | 0.997 | 1.000 | 0 | 0.997 |
| all | 377 | 0 | 0.995 | 1.000 | 0 | 0.997 |

## Cost and latency

- Tokens: 1,390,405 input (0 of them served from Vertex's implicit cache), 22,572 output, 1,973 thinking
- Estimated cost: $1.13 at $0.75/1M input and $3.75/1M output+thinking (list price, no caching discount)
- Latency per call: median 2.11 s, p95 13.37 s (concurrency 4)

## Mistakes

All mistakes by kind (label mistakes first; a needs_response mistake is only counted when the label is right):

- new_request: needs_response extra reply: 1
- proposed_times → reschedule: 1
- new_request → assistant_handoff: 1

### The 20 most informative

Spread over the kinds of error, worst first: scheduling missed, false alarms, wrong scheduling label, then needs_response.

| message_id | user | subject | true | predicted | needs_response true → pred | Gemini's reason |
|---|---|---|---|---|---|---|
| 3ba2c3724b1721c5 | user_04 | Mid-term feedback | new_request | assistant_handoff | False → False | Fiona delegates the scheduling of the meeting to Callum Reid, who will book the user in, making this an assistant handoff under D5 and T2 with no immediate response required from the user under NR1. |
| e3f8c97e38dafbee | user_02 | Monday 10/19 | proposed_times | reschedule | True → True | The sender cancels the confirmed 10/19 meeting and directively moves the meeting to October 26 at 10:00 (D4, PR1, NR9). |
| 2b1bc892af42b94d | user_02 | Offer negotiation advice | new_request | new_request | False → True | Dana introduces Marcus to Grace Kim to meet directly regarding offer advice (E17), which carries a label of new_request and requires a response as neither party was exclusively assigned to reach out (NR10). |
