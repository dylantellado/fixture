# Gemini baseline: gemini-3.8-flash on the training data

## Run

- Model: `gemini-3.8-flash` (served as `gemini-3.8-flash`), Vertex AI `fixture-ac215-96dhbm` / `global`, temperature 0, structured JSON output, thinking budget model default
- Labeling rules: v1.3 (`docs/data/labeling_rules.md`, without the "Not adopted" and "Change log" sections); annotations follow v1.2
- Rules text sent: sha256 `fb5409200b4443d645bed6a55b9aa2b7e52ac36705ff012621c17438273103e4`
- Git commit: `cd73ebb5aa533ad9ecec19361812696895e59a7a`
- Date: 2026-10-29 19:27 UTC
- Messages: 377, users user_01, user_02, user_03, user_04
- Failures: 0 (left out of every score below)

## Labels

**Accuracy: 0.984** on 377 messages.

| label | precision | recall | f1 | support |
|---|---|---|---|---|
| new_request | 1.000 | 0.980 | 0.990 | 51 |
| proposed_times | 1.000 | 0.975 | 0.987 | 79 |
| acceptance | 0.990 | 0.990 | 0.990 | 101 |
| reschedule | 1.000 | 0.976 | 0.988 | 41 |
| assistant_handoff | 0.750 | 1.000 | 0.857 | 9 |
| none | 0.979 | 0.990 | 0.984 | 96 |

### Confusion matrix (rows: true label, columns: predicted)

| true \ pred | new_request | proposed_times | acceptance | reschedule | assistant_handoff | none |
|---|---|---|---|---|---|---|
| new_request | 50 | 0 | 0 | 0 | 0 | 1 |
| proposed_times | 0 | 77 | 0 | 0 | 2 | 0 |
| acceptance | 0 | 0 | 100 | 0 | 1 | 0 |
| reschedule | 0 | 0 | 0 | 40 | 0 | 1 |
| assistant_handoff | 0 | 0 | 0 | 0 | 9 | 0 |
| none | 0 | 0 | 1 | 0 | 0 | 95 |

### Scheduling vs `none`

- **Recall on the five scheduling labels combined: 0.993** (2 of 281 scheduling emails predicted `none`, the worst error)
- False alarms: 1 of 96 `none` emails predicted as a scheduling label
- Hard negatives: not scored. `data/source/annotations.jsonl` doesn't mark hard negatives (only the generation outlines in `docs/data/generation/` mention some in prose).

## needs_response

- Accuracy 0.997, precision 0.991, recall 1.000 (109 messages need a response)
- Replies missed (true, predicted false): 0; extra (false, predicted true): 1

## By user

| users | messages | failures | label_acc | sched_recall | sched_as_none | nr_acc |
|---|---|---|---|---|---|---|
| user_01 | 100 | 0 | 0.990 | 0.986 | 1 | 1.000 |
| user_02 | 97 | 0 | 0.990 | 0.986 | 1 | 0.990 |
| user_03 | 90 | 0 | 0.967 | 1.000 | 0 | 1.000 |
| user_04 | 90 | 0 | 0.989 | 1.000 | 0 | 1.000 |
| user_01–03 | 287 | 0 | 0.983 | 0.991 | 2 | 0.997 |
| all | 377 | 0 | 0.984 | 0.993 | 2 | 0.997 |

## Cost and latency

- Tokens: 1,139,323 input (0 of them served from Vertex's implicit cache), 20,965 output, 131,129 thinking
- Estimated cost: $1.42 at $0.75/1M input and $3.75/1M output+thinking (list price, no caching discount)
- Latency per call: median 3.82 s, p95 20.50 s (concurrency 4)

## Mistakes

All mistakes by kind (label mistakes first; a needs_response mistake is only counted when the label is right):

- proposed_times → assistant_handoff: 2
- reschedule → none (scheduling missed): 1
- new_request → none (scheduling missed): 1
- new_request: needs_response extra reply: 1
- none → acceptance (false alarm): 1
- acceptance → assistant_handoff: 1

### The 20 most informative

Spread over the kinds of error, worst first: scheduling missed, false alarms, wrong scheduling label, then needs_response.

| message_id | user | subject | true | predicted | needs_response true → pred | Gemini's reason |
|---|---|---|---|---|---|---|
| b596f36dd0aba440 | user_02 | Mock technical interview? | new_request | none | False → False | The message inquires about career center services rather than asking to set up a meeting (D6), and needs_response is false because the user sent the email (NR1). |
| dedb6df0524a507a | user_01 | STAT 142: office hours this week | reschedule | none | False → False | This is an announcement of office hours sent to a group mailing list, which is classified as none under E3 and requires no response under NR1. |
| b69c3b5f0b813da8 | user_03 | sections?? | none | acceptance | False → False | The user confirms and agrees to the proposed section assignment and time (D3), and needs_response is false because the message was sent by the user (NR1). |
| 166482ab09374bcc | user_03 | Brightwater final round: Chicago | acceptance | assistant_handoff | False → False | The email provides the first notice handing coordination of the visit and schedule to recruiting coordinator Dev Shah (D5, T2) while restating the already agreed date (E14), requiring no reply from the user as Dev will follow up directly (NR1). |
| 76885a71c68ac079 | user_03 | Recurring meetings with Dr. Achebe | proposed_times | assistant_handoff | True → True | Irene is coordinating on Dr. Achebe's behalf as the initial notice of a handoff (D5, E17, T2, PR3), and the user must respond to confirm the proposed schedule (NR1). |
| 9d32fed4db2eaa52 | user_04 | Monthly check-in with Ruth | proposed_times | assistant_handoff | True → True | Owen is coordinating a meeting on Ruth's behalf as the initial scheduling contact (E17, T2, D5), and Lena must reply to confirm whether the suggested time works (NR1). |
| 2b1bc892af42b94d | user_02 | Offer negotiation advice | new_request | new_request | False → True | This is an introduction connecting the user with a specialist who will meet with him directly, making it a new request under E17, and the user must coordinate to set up a time under NR1. |
