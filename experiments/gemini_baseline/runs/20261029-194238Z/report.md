# Gemini baseline: gemini-3.8-flash on the training data

## Run

- Model: `gemini-3.8-flash` (served as `gemini-3.8-flash`), Vertex AI `fixture-ac215-96dhbm` / `global`, temperature 0, structured JSON output, thinking budget 128
- Labeling rules: v1.3 (`docs/data/labeling_rules.md`, without the "Not adopted" and "Change log" sections); annotations follow v1.2
- Rules text sent: sha256 `fb5409200b4443d645bed6a55b9aa2b7e52ac36705ff012621c17438273103e4`
- Git commit: `cd73ebb5aa533ad9ecec19361812696895e59a7a (uncommitted changes)`
- Date: 2026-10-29 19:42 UTC
- Messages: 377, users user_01, user_02, user_03, user_04
- Failures: 0 (left out of every score below)

## Labels

**Accuracy: 0.989** on 377 messages.

| label | precision | recall | f1 | support |
|---|---|---|---|---|
| new_request | 1.000 | 0.980 | 0.990 | 51 |
| proposed_times | 1.000 | 0.975 | 0.987 | 79 |
| acceptance | 0.990 | 1.000 | 0.995 | 101 |
| reschedule | 1.000 | 1.000 | 1.000 | 41 |
| assistant_handoff | 0.818 | 1.000 | 0.900 | 9 |
| none | 0.990 | 0.990 | 0.990 | 96 |

### Confusion matrix (rows: true label, columns: predicted)

| true \ pred | new_request | proposed_times | acceptance | reschedule | assistant_handoff | none |
|---|---|---|---|---|---|---|
| new_request | 50 | 0 | 0 | 0 | 0 | 1 |
| proposed_times | 0 | 77 | 0 | 0 | 2 | 0 |
| acceptance | 0 | 0 | 101 | 0 | 0 | 0 |
| reschedule | 0 | 0 | 0 | 41 | 0 | 0 |
| assistant_handoff | 0 | 0 | 0 | 0 | 9 | 0 |
| none | 0 | 0 | 1 | 0 | 0 | 95 |

### Scheduling vs `none`

- **Recall on the five scheduling labels combined: 0.996** (1 of 281 scheduling emails predicted `none`, the worst error)
- False alarms: 1 of 96 `none` emails predicted as a scheduling label
- Hard negatives: not scored. `data/source/annotations.jsonl` doesn't mark hard negatives (only the generation outlines in `docs/data/generation/` mention some in prose).

## needs_response

- Accuracy 0.992, precision 0.973, recall 1.000 (109 messages need a response)
- Replies missed (true, predicted false): 0; extra (false, predicted true): 3

## By user

| users | messages | failures | label_acc | sched_recall | sched_as_none | nr_acc |
|---|---|---|---|---|---|---|
| user_01 | 100 | 0 | 1.000 | 1.000 | 0 | 1.000 |
| user_02 | 97 | 0 | 0.990 | 0.986 | 1 | 0.969 |
| user_03 | 90 | 0 | 0.978 | 1.000 | 0 | 1.000 |
| user_04 | 90 | 0 | 0.989 | 1.000 | 0 | 1.000 |
| user_01–03 | 287 | 0 | 0.990 | 0.995 | 1 | 0.990 |
| all | 377 | 0 | 0.989 | 0.996 | 1 | 0.992 |

## Cost and latency

- Tokens: 1,139,323 input (0 of them served from Vertex's implicit cache), 22,278 output, 2,412 thinking
- Estimated cost: $0.95 at $0.75/1M input and $3.75/1M output+thinking (list price, no caching discount)
- Latency per call: median 2.35 s, p95 14.05 s (concurrency 4)

## Mistakes

All mistakes by kind (label mistakes first; a needs_response mistake is only counted when the label is right):

- new_request: needs_response extra reply: 3
- proposed_times → assistant_handoff: 2
- new_request → none (scheduling missed): 1
- none → acceptance (false alarm): 1

### The 20 most informative

Spread over the kinds of error, worst first: scheduling missed, false alarms, wrong scheduling label, then needs_response.

| message_id | user | subject | true | predicted | needs_response true → pred | Gemini's reason |
|---|---|---|---|---|---|---|
| b596f36dd0aba440 | user_02 | Mock technical interview? | new_request | none | False → False | The user is inquiring about career center services rather than asking to schedule a specific meeting (D6), and since it was sent by the user, needs_response is false (NR1). |
| b69c3b5f0b813da8 | user_03 | sections?? | none | acceptance | False → False | The user confirms the proposed section assignment under D3, and as the sender of the message, needs_response is false per NR1. |
| 76885a71c68ac079 | user_03 | Recurring meetings with Dr. Achebe | proposed_times | assistant_handoff | True → True | The sender is coordinating scheduling on Dr. Achebe's behalf as the first notice of handoff per rules D5, E17, and T2, while proposing times that require the user to confirm per rule NR1. |
| 9d32fed4db2eaa52 | user_04 | Monthly check-in with Ruth | proposed_times | assistant_handoff | True → True | Owen is coordinating on Ruth's behalf (T2, E17, D5), which takes priority over the proposed times (PR3), and requires Lena to confirm or reply (NR1). |
| 6036baac6f4ce32a | user_02 | Mock technical interview? | new_request | new_request | False → True | Dana introduces Marcus to Nadia to conduct the mock interview directly, which functions as an introduction request under E17 and D1, requiring a response under NR1. |
| 9d817cdfb67a8e11 | user_02 | Meet Leah | new_request | new_request | False → True | This is an introductory email connecting Marcus with Leah to set up a meeting where Leah will meet Marcus herself, so it is classified as new_request per E17 and D1, requiring a response per NR1. |
| 2b1bc892af42b94d | user_02 | Offer negotiation advice | new_request | new_request | False → True | This is an introduction connecting the user with Grace Kim to meet directly about offer negotiation (E17, D1), and the user needs to respond to coordinate a time (NR1). |
