# Eval set v1: held-out test set for the email classifier

**Never tune on this set.** Don't use it for prompt tuning, few-shot examples,
picking a model or threshold, or training. It is for the final measurement only. If
you look at its errors to improve the classifier, the scores on it stop meaning
anything, and we need a v2.

It measures whether a classifier that labels each email with one of the six
scheduling labels (see the README's Data contract) generalizes beyond the style of our
training corpus (`data/source/`, data-v1). So it was written to look different: new
users and contacts, other writing styles, a later date range, and many hard negatives.

## Files

| File | What |
|---|---|
| `users.json` | 4 fictional students, `eval_01` to `eval_04` (same format as `data/source/users.json`) |
| `threads.jsonl` | 140 threads, 298 messages, in the source-thread format from the Data contract. `label` is the final label. Nothing else is in it, so a classifier never sees the notes below. |
| `annotations.jsonl` | One line per message, keyed by `user_id` + `thread_id` + `position` (0-based index in the thread): `writer_agent`, `category`, `difficulty` (easy/hard), `needs_response`, `intended_label` (writer), `labeler_label` (independent labeler), `final_label`, `rationale`, `rules_version` (the version of `docs/data/labeling_rules.md` the values follow) |
| `changes_rules_v1.0.json`, `changes_rules_v1.1.json`, `changes_rules_v1.2.json` | Every change made when the set was re-checked against labeling rules v1.0, v1.1 and v1.2 (see below) |
| `check.py` | Checks the set (format, rules below, counts, agreement, leakage). `python3 data/eval/v1/check.py final` |
| `build.py` | How the writers' drafts became the two files above (merge and renumber, apply labels, apply rule changes) |

The writers' drafts (`work/`) and the pipeline output (`processed/`) stay local and are git-ignored.

## Who's in it

All four students are at **Ellery University** (fictional, `ellery.example`, US Eastern
time). The training users are at "the College".

| user_id | Name | Who | Messages |
|---|---|---|---|
| eval_01 | Talia Brennan | premed senior applying for gap-year research jobs and shadowing | 78 |
| eval_02 | Devon Kowalczyk | MBA-track economics junior networking in consulting | 71 |
| eval_03 | Noor Haddad | PhD student chairing a graduate symposium, scheduling across time zones | 80 |
| eval_04 | Jalen Whitaker | varsity swimmer interviewing for data and quant internships around meets | 69 |

Messages are dated **Nov 2 to Dec 15, 2026** (training: Sep 1 to Oct 18), with US standard
time and European winter time offsets.

## How it was made

1. **Six writer agents** (Claude subagents) worked in parallel. Each got a shared brief
   (format, label rules, fictional-data rules) plus its own style, label quota and the
   hard-negative categories it owned. None saw the training data or the other writers'
   briefs. Different models were used so the styles differ:

   | Writer | Model | Style | Messages |
   |---|---|---|---|
   | `terse` | Sonnet | lowercase one-liners, typos, implicit acceptances and reschedules | 50 |
   | `corp` | Opus | recruiting and HR: templated, long signatures, legal footers, ATS mail, executive assistants | 51 |
   | `acad` | Opus | professors, lab managers, admins: long, indirect, committee scheduling | 53 |
   | `auto` | Haiku | automated mail full of scheduling words (all hard negatives) | 40 |
   | `intl` | Sonnet | non-native English, 24-hour times, DD/MM dates, other time zones | 47 |
   | `adv` | Opus | adversarial edge cases, including prompt-injection text | 57 |

2. `build.py merge` combined the drafts and renumbered threads `t001`, `t002`, ... per user
   in order of their first message, so a thread id doesn't reveal its writer.
3. **One independent labeler agent** (Opus) labeled all 298 messages. It saw only the
   threads with labels and notes removed, plus the written label rules. It never saw the
   writers' briefs, intended labels or rationales.
4. Where the writer and labeler disagreed, the final label was decided by the written
   rules (below) and recorded in the rationale. `build.py finalize` then wrote `threads.jsonl`
   and `annotations.jsonl`.
5. `check.py final`, `src/ingest/validate.py`, `ingest` and `preprocess` were run on the result.
6. **Re-checks against labeling rules v1.0, v1.1 and v1.2.** For v1.0 and v1.1, an independent agent applied the rules to all 298 messages without seeing the current values. For v1.2, which added only E17 and NR9, I checked every message those two rules could reach: every `assistant_handoff`, every introduction, and every received move marked `false`. I settled each difference by the written rules, recorded the changes in `changes_rules_v1.*.json`, and applied them with `build.py apply-changes` (see "Changes for labeling rules").

## Label rules

**[`docs/data/labeling_rules.md`](../../../docs/data/labeling_rules.md) (v1.2) is the
source of truth** for every `label` and `needs_response` in this set. Every value follows
it (`rules_version` in `annotations.jsonl`). Its "Not adopted" section lists
proposals that were deliberately left out; they are not applied here.

Before v1.0, the writers and the first labeler had worked under two clarifications that v1.0
replaced: vague pleasantries were `none` (now E8: `new_request`), and cold sales asks were
labeled by intent (now E9: `none`).

## Final counts

These are under labeling rules v1.2.

| Label | Messages | Share |
|---|---|---|
| `none` | 117 (82 hard, 35 easy) | 39% |
| `proposed_times` | 42 | 14% |
| `new_request` | 38 | 13% |
| `acceptance` | 36 | 12% |
| `reschedule` | 35 | 12% |
| `assistant_handoff` | 30 | 10% |
| **Total** | **298** in 140 threads | |

- Every label has at least 30 messages (`assistant_handoff` is exactly 30), and hard negatives are 70.1% of `none` (82/117), just above the 70% floor.
- **Difficulty:** 130 hard and 168 easy.
- **`needs_response`:** 68 true and 230 false. 91 of the 298 messages were sent by the users
  themselves, and those are always false (NR1).
- **Categories:** 93 categories. `python3 data/eval/v1/check.py final` prints the counts per
  category, writer and user. The largest hard-negative groups are the automated ones:
  `promo_webinar`, `sales_demo_blast`, `calendar_notification`, `booking_confirmation`,
  `appointment_reminder`, `delivery_window`, `travel_reminder`, `class_schedule_change`,
  `deadline_reminder`, `meeting_recap`, `newsletter_save_the_date` and `out_of_office`.
  Writer-owned hard negatives include `quoted_scheduling_noise`, `vague_catch_up`,
  `tz_logistics_after_confirmed`, `lab_meeting_agenda`, `ats_status_update` and `offer_deadline`.
- **Prompt injection:** 8 messages contain text aimed at an AI assistant:
  - `eval_01/t004/0` and `t021/0`
  - `eval_02/t023/0`
  - `eval_03/t033/0`, `t035/0` and `t035/1`
  - `eval_04/t011/0` and `t011/1`

  They have category `prompt_injection` and are labeled by their real intent (E12): 6 `none`
  (two of them cold sales pitches, E9), 1 `new_request`, 1 `reschedule`.

## Labeler agreement and disagreements

The writer and the independent labeler agreed on **295 of 298 messages (99.0%)**. That was
before labeling rules v1.0, v1.1 and v1.2, which changed 8, 2 and 4 more labels. The final
label now matches the writer's intended label on 281 of 298 messages.

That number is surely higher than two people would get. Both sides are Claude models
working from the same written rules, and the writers wrote each message to fit a label.
Treat it as a check that the labels follow the rules, not as a measure of how ambiguous
real email is. A person should spot-check a sample, starting with the lists below.

All three disagreements were kept, because they are the most useful cases:

| Message | Writer | Labeler | Final | Why |
|---|---|---|---|---|
| `eval_02/t002/4` "cant fri 4 got the sterling quay dinner. sat 11?" | reschedule | proposed_times | `proposed_times` | The previous message already moved the confirmed session. This reply counters the new slot, so it is labeled by what it does, like `eval_03/t011/2`. |
| `eval_02/t012/0` assistant forwards her boss's "find 30 min with Devon" note and asks for availability | new_request | assistant_handoff | `assistant_handoff` | It is the first message telling Devon that scheduling goes through the assistant, the same as the other assistants who introduce themselves. |
| `eval_04/t003/0` registrar: STAT 320 lecture moves from 9:00 to 11:00 | none | reschedule | `reschedule` | A group notice moving a recurring class meeting matches the group-announcement rule. The two room-only registrar notices (`eval_01/t023/0`, `eval_03/t006/0`) keep the same time and stay `none`. |

## Changes for labeling rules

### v1.0

18 changes to 16 messages. Rule ids are from `docs/data/labeling_rules.md`. `message_id` is the
id `preprocess` gives the message (Data contract rule), and the second column is
`user_id/thread_id/position`.

| message_id | Message | Field | Old → new | Rule |
|---|---|---|---|---|
| `90fa8d4b0003fd6a` | eval_01/t015/1 | label | `none` → `new_request` | E8 |
| `d196fa3edf5af5d0` | eval_01/t021/0 | label | `proposed_times` → `none` | E9 |
| `baec1dbda3011a40` | eval_01/t021/1 | label | `new_request` → `none` | E9 |
| `f18c7049b14478c3` | eval_01/t028/2 | label | `none` → `new_request` | E8 |
| `9f046a187b3abd8c` | eval_02/t032/0 | label | `none` → `new_request` | E8 |
| `073b191de6af31b0` | eval_02/t032/2 | label | `none` → `new_request` | E8 |
| `8822d1db1dbc7a60` | eval_03/t033/0 | label | `new_request` → `none` | E9 |
| `0d06a77d326e5d19` | eval_04/t026/0 | label | `none` → `acceptance` | D3 |
| `0f2371a69ce78c29` | eval_01/t007/2 | needs_response | `true` → `false` | NR1 |
| `90fa8d4b0003fd6a` | eval_01/t015/1 | needs_response | `false` → `true` | NR1 |
| `ff1269a6bd353727` | eval_01/t018/1 | needs_response | `true` → `false` | NR1 |
| `21b0d7a30432234b` | eval_02/t004/0 | needs_response | `true` → `false` | NR4 |
| `62d86e210a67aaef` | eval_02/t012/2 | needs_response | `false` → `true` | NR3 |
| `2ba96d167cbf9c9a` | eval_02/t022/2 | needs_response | `true` → `false` | NR2 |
| `9f046a187b3abd8c` | eval_02/t032/0 | needs_response | `false` → `true` | NR1 |
| `40c25c86ad629dac` | eval_03/t029/1 | needs_response | `true` → `false` | NR2 |
| `0f0900d43f37a498` | eval_03/t031/1 | needs_response | `true` → `false` | NR2 |
| `f0f299e30ec499f9` | eval_04/t024/0 | needs_response | `true` → `false` | NR1 |

Why each changed is in that message's `rationale` and in `changes_rules_v1.0.json`.

### v1.1

10 changes to 9 messages, from the rules adopted in v1.1 (E13 to E16, NR3, NR5 to NR8).

| message_id | Message | Field | Old → new | Rule |
|---|---|---|---|---|
| `242ee72c955e52c6` | eval_01/t012/1 | label | `new_request` → `proposed_times` | E16 |
| `21b0d7a30432234b` | eval_02/t004/0 | label | `new_request` → `proposed_times` | E16 |
| `21b0d7a30432234b` | eval_02/t004/0 | needs_response | `false` → `true` | NR5 |
| `f18c7049b14478c3` | eval_01/t028/2 | needs_response | `false` → `true` | NR8 |
| `073b191de6af31b0` | eval_02/t032/2 | needs_response | `false` → `true` | NR8 |
| `ceae82382155e138` | eval_03/t001/2 | needs_response | `false` → `true` | NR3 |
| `ec44b5c988e39d56` | eval_03/t005/1 | needs_response | `false` → `true` | NR3 |
| `4e4b812a6be79657` | eval_03/t008/3 | needs_response | `false` → `true` | NR3 |
| `1c1469a06714b27f` | eval_03/t010/3 | needs_response | `false` → `true` | NR3 |
| `8fe96589b1fc4c72` | eval_03/t019/2 | needs_response | `false` → `true` | NR3 |

The v1.1 re-check agent proposed 3 more label changes, which were **not** made:
- **`eval_03/t020/2` `reschedule` → `proposed_times`:** the same T1 case as in v1.0.
- **`eval_03/t029/2` `assistant_handoff` → `none`:** a reading of T2's "first notice". No v1.1 rule touches it, and two earlier passes agreed on `assistant_handoff`.
- **`eval_04/t026/0` `acceptance` → `none` (E14):** E14 needs a time that was already agreed, and nothing in the thread shows that agreement (E15: agreement isn't inferred from outside the new text). It stays `acceptance` (D3) and is listed below as a known ambiguity.

E13 (still on? check-ins) and E14 (restated agreed time) changed nothing. The only "still on?"
messages (`eval_01/t033/0`, `eval_04/t014/0`) are sent by the users, so they are `false` under
NR1. The restated-time messages were already `none`/`false`. E15 changed nothing either:
every message whose earlier agreement is only quoted is labeled by what its own new text
says (e.g. `eval_04/t019/0` "I need to move our check-in on Thursday at 2").

Why each v1.1 change was made is in the `rationale` and in `changes_rules_v1.1.json`.

### v1.2

7 changes to 7 messages, from E17 (introductions) and NR9 (directive moves).

| message_id | Message | Field | Old → new | Rule |
|---|---|---|---|---|
| `503d3e0e97c52102` | eval_01/t002/2 | label | `assistant_handoff` → `new_request` | E17 |
| `1f107a4bca314365` | eval_02/t023/1 | label | `assistant_handoff` → `new_request` | E17 |
| `6f2be3e499059b8c` | eval_03/t017/1 | label | `assistant_handoff` → `new_request` | E17 |
| `93739e6e9683654e` | eval_04/t019/1 | label | `assistant_handoff` → `new_request` | E17 |
| `0f2371a69ce78c29` | eval_01/t007/2 | needs_response | `false` → `true` | NR9 |
| `71d87dee9a480656` | eval_03/t020/0 | needs_response | `false` → `true` | NR9 |
| `c2f6cd8f9415a924` | eval_04/t025/0 | needs_response | `false` → `true` | NR9 |

- **E17:** every `assistant_handoff` was checked. The ones that stay are an assistant, scheduler
  or coordinator arranging a meeting with someone else (e.g. `eval_01/t011/1`, where the clinic
  coordinator holds the doctor's template, and `eval_04/t030/1`, where the postdoc finds time
  "for the three of us").
- **NR9:** every received move marked `false` was checked. Moves sent to a mailing list or group
  address (`eval_01/t017/1`, `eval_02/t019/0`, `eval_03/t016/1`, `eval_04/t011/1`,
  `eval_04/t022/1`), the registrar notice, cancellations (NR2) and moves the user is only
  copied on stay `false`.
- **The 3 labels kept under v1.1** (`eval_03/t020/2`, `eval_03/t029/2`, `eval_04/t026/0`) are
  unchanged.

The re-check agent proposed one more label change, which was **not** made:
`eval_03/t020/2` `reschedule` → `proposed_times`. Noor accepted the new Wednesday 5pm time in
the previous message, so asking to move it again is `reschedule` under T1's last sentence.

The edge-case rules were checked on every message they could apply to:
- **E8:** all catch-up wording.
- **E9:** every cold or unsolicited ask. Automated demo blasts were already `none`.
- **E10:** all 6 messages with a forwarded block. None forwards meeting times the user is
  meant to act on. `eval_02/t006/0` and `eval_02/t007/0` forward info-session invitations,
  which are group events (E3).
- **E11:** every `none` that is a personal message.

## Known ambiguities

These follow the adopted rules (v1.2) but are close calls. Where a proposal that was not
adopted would bear on one, its id is given (final label in brackets):

- `eval_01/t016/0` [assistant_handoff]: "get the time from my roommate, she's booking the room" (P7).
- `eval_03/t003/0` [none]: a thank-you that says "we'll be in touch in December to arrange a call" (P6).
- `eval_03/t016/0` [none]: a seminar announcement with a sign-up sheet for meeting the speaker (P8).
- `eval_03/t002/0` [new_request]: Noor's own sponsorship pitch. E9 is about sales asks to the user (P9).
- `eval_03/t010/1`, `eval_03/t021/0`, `eval_03/t029/2` [assistant_handoff]: a secretary, a conference secretariat or a chief of staff takes over and asks for availability. In `t029/2`, the previous message had already named her, so "first notice" (T2) is a judgment call.
- `eval_03/t011/2` [new_request]: turns down the replacement times in a reschedule and asks for more (T1, E7).
- `eval_03/t020/2` [reschedule]: asks to move a group sync that was confirmed one message earlier (T1). Two re-check agents read it as `proposed_times`.
- `eval_04/t026/0` [acceptance]: "Confirming your final round" is the only place in the thread that sets the time. E14 would make it `none` only if an earlier agreement were visible.
- `eval_01/t012/1` [proposed_times]: a person, not a system, sends the booking link. E16 covers both.
- `eval_01/t028/2` [new_request, needs_response true]: mostly "I'll get back to you", plus "we should get the whole lab out for coffee sometime" (E8, NR8).
- `eval_01/t018/1` [assistant_handoff, needs_response false]: the professor copies his assistant who will arrange the call, and adds "please revert to her". It could be read as asking the user to write first.
- `eval_02/t023/1` [new_request]: Devon sends Sunniva to Ravi's case group rather than introducing a one-to-one meeting (E17).
- `eval_04/t019/1` [new_request]: the advisor's message also relays Jalen's free times to the coordinator. They aren't offered to Jalen, so it isn't `proposed_times`.

## Limitations

- **Everything is written by language models.** It looks different from data-v1, but it is
  still model-written email. Real inboxes are messier and about 90% non-scheduling, while this
  set is 39% `none`. Report per-label precision and recall rather than accuracy alone.
- **`needs_response` follows NR1 to NR9 (v1.2).** Two independent re-checks of all 298 messages
  back it up, and the close calls are listed above. Expect some disagreement from a human
  reader on "must reply".
- **`category` is the writer's tag** and wasn't changed when a label changed (e.g.
  `eval_02/t002/4` keeps `implicit_reschedule`).
- **Writer style tracks the label mix.** 39 of the 40 `auto` messages are `none` (the
  exception is the registrar lecture change), so per-writer scores mix style and label difficulty.

## Checks run

- **No leakage from the training data.** Normalized message bodies were compared with every
  body in `data/source/`. The highest similarity is 0.579 (difflib ratio, 1.0 = identical):
  short phone replies that share only the "Sent from my iPhone" footer and the quote-header
  pattern.
- **No reused names.** No person, organization or domain name from `data/source/` or
  `docs/data/generation/` is used. `check.py` flags these, and the writers renamed the
  handful it caught. One name that two writers both invented for different people was also
  renamed.
- **Fictional data only.** Every address uses a `.example` domain, every phone number is in
  555-01xx, and every timestamp is in the window with the right weekday for its date.
- **The pipeline accepts it.** `src/ingest/validate.py` (contract checks) reports 0 errors. Run
  `ingest` and `preprocess` on a copy (below) and they keep all 140 threads and 298 messages,
  and no cleaned body is empty. Don't use `validate.py --generated`, because its date window
  and time zones are data-v1's.

To rerun the pipeline without touching `data/raw/` or `data/processed/`:

```sh
EVAL_RUN=$(mktemp -d) && mkdir -p "$EVAL_RUN/source"
cp data/eval/v1/users.json "$EVAL_RUN/source/users.json"
cp data/eval/v1/threads.jsonl "$EVAL_RUN/source/generated_threads.jsonl"
(cd src/ingest && DATA_DIR="$EVAL_RUN" uv run python main.py)
(cd src/preprocess && DATA_DIR="$EVAL_RUN" uv run python main.py)
mkdir -p data/eval/v1/processed && cp "$EVAL_RUN"/processed/* data/eval/v1/processed/
```
