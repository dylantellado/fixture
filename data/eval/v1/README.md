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
| `annotations.jsonl` | One line per message, keyed by `user_id` + `thread_id` + `position` (0-based index in the thread): `writer_agent`, `category`, `difficulty` (easy/hard), `needs_response`, `intended_label` (writer), `labeler_label` (independent labeler), `final_label`, `rationale` |
| `check.py` | Checks the set (format, rules below, counts, agreement, leakage). `python3 data/eval/v1/check.py final` |
| `build.py` | How the writers' drafts became the two files above (merge and renumber, then apply labels) |

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

## Label rules

The same rules as the training corpus (`docs/data/generation/corpus_plan.md`: label
definitions, priority rule, edge cases), plus these clarifications, decided for this set
and given to both writers and the labeler:

- A vague pleasantry with no real ask ("we should grab coffee sometime!") is `none`. A real
  ask to meet that names no times ("could we find time next week to catch up?") is `new_request`.
- Cold sales or recruiting emails that really ask for a meeting are labeled by intent
  (`new_request` or `proposed_times`, category `unsolicited_request` or `prompt_injection`).
  Mass marketing that only invites people to book a demo or a seat is `none`.
- Quoted history and forwarded blocks are context. The message is labeled by its own new
  text, except that a forwarder's note is read together with what it forwards.
- Text aimed at an "AI assistant" or "SYSTEM" is ignored. The message is labeled by what it
  really asks of a human reader.

Two more were settled while resolving disagreements (see below): follow-up messages in a
reschedule are labeled by what they do, and a registrar notice that moves a class to a new
time counts as a group announcement moving a recurring meeting.

## Final counts

| Label | Messages | Share |
|---|---|---|
| `none` | 119 (84 hard, 35 easy) | 40% |
| `proposed_times` | 41 | 14% |
| `acceptance` | 35 | 12% |
| `reschedule` | 35 | 12% |
| `assistant_handoff` | 34 | 11% |
| `new_request` | 34 | 11% |
| **Total** | **298** in 140 threads | |

- Every label has at least 30 messages, and hard negatives are 71% of `none`.
- **Difficulty:** 130 hard and 168 easy.
- **`needs_response`:** 61 true and 237 false. 91 of the 298 messages were sent by the users
  themselves, and those are always false.
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

  They have category `prompt_injection` and are labeled by their real intent (4 `none`,
  2 `new_request`, 1 `proposed_times`, 1 `reschedule`).

## Labeler agreement and disagreements

The writer and the independent labeler agreed on **295 of 298 messages (99.0%)**.

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

## Known ambiguities

The labeler agreed with the writer on these but marked them UNSURE (final label in brackets):

- `eval_01/t002/2` [assistant_handoff]: the PI asks the research coordinator to find time with Talia, but she is also the person Talia meets.
- `eval_01/t016/0` [assistant_handoff]: "get the time from my roommate, she's booking the room".
- `eval_02/t004/0` [new_request]: an automated interview invite with a self-scheduling link and no times. It could be read as automated `none`.
- `eval_02/t032/2` [none]: "coffee in the new year", with no real ask.
- `eval_03/t003/0` [none]: a thank-you that says "we'll be in touch in December to arrange a call".
- `eval_03/t010/1`, `eval_03/t021/0`, `eval_03/t029/2` [assistant_handoff]: a secretary, a conference secretariat or a chief of staff takes over and asks for availability (one gives a broad window).
- `eval_03/t011/2` [new_request]: turns down the replacement times in a reschedule and asks for more.
- `eval_03/t017/1` [assistant_handoff]: a forwarded deadline notice whose real point is asking a postdoc to find an hour with Noor.
- `eval_03/t020/2` [reschedule]: moves a sync that was confirmed one message earlier.
- `eval_04/t026/0` [none]: a recruiter "confirms" a final round set earlier and adds instructions. It could be read as `acceptance`.

The writers also flagged these:

- "Still on for Thursday at 3?" check-ins before a set meeting (`confirmation_question`) are `none`.
- `tz_logistics_after_confirmed` messages that restate an agreed time are `none`, not `acceptance`.
- In a few threads, the time being accepted or moved appears only in quoted history from before Nov 2, not in an earlier message of the thread.
- The `auto` calendar notice "Event moved to Thu 2:00 PM" is `none` (calendar invite text), while the registrar's lecture-time change is `reschedule`.

## Limitations

- **Everything is written by language models.** It looks different from data-v1, but it is
  still model-written email. Real inboxes are messier and about 90% non-scheduling, while this
  set is 40% `none`. Report per-label precision and recall rather than accuracy alone.
- **`needs_response` was set by the writers only.** Nobody checked it independently, and the
  writers aren't fully consistent (for example, cancellations without a new time are true in
  some threads and false in others). Use it for rough analysis, not as a headline metric.
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
