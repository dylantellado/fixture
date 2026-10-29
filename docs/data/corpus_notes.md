# Fake email corpus: notes

What's in the generated corpus, and the questions it can answer. The full plan
it was written from is in [`generation/`](generation/corpus_plan.md). Everything
is fictional: people, firms, addresses (`.example` domains) and phone numbers
(reserved fictional ranges).

**Size:** 4 users, 160 threads (40 each), 377 messages, Sep 1 to Oct 18, 2026.
The data-v1 inputs are committed in `data/source/` (DVC will take over once its storage bucket exists); a small sample is in
`samples/generated_threads_sample.jsonl`.

## Users

| user_id | Name | Who | Time zone |
|---|---|---|---|
| user_01 | Priya Shah | Economics junior, investment banking recruiting | ET |
| user_02 | Marcus Bell | CS senior, software new-grad jobs and startups | ET (many contacts PT) |
| user_03 | Sofia Okafor | Data science master's, consulting recruiting, TA for STAT 142 | ET |
| user_04 | Lena Fischer | International sophomore, study abroad in London | London |

## Recurring contacts and habits

Each habit appears in several threads, so a search has a clear answer.

| User | Contact | Habit |
|---|---|---|
| user_01 | Dana Whitfield (career advisor) | in person, **Tuesdays 3:00 or 3:30 pm**, Wexley Hall Room 214 |
| user_01 | Prof. Elena Vasquez | office hours **Tue/Thu 4 to 5 pm, 20-minute slots**; head TA Theo Marsh covers when she travels |
| user_01 | Rohan Mehta (alum, London) | **phone only, mornings ET** (one in-person exception, Nov 9 in Boston) |
| user_01 | Claire Donnelly (mentor) | Sunday 7 pm calls; **always reschedules once** |
| user_01, user_02 | Jordan Lee → Tess Navarro (Larkmoor Capital) | Jordan invites, **Tess schedules with exactly three slots** |
| user_02 | Dana Whitfield | **video, Fridays 11 am** |
| user_02 | Aisha Rahman (startup founder, SF) | **Wed or Fri afternoons PT** only |
| user_02 | Tom Haskell (Pinecrest Labs) | **hands scheduling to his assistant Gwen Liu** |
| user_02 | Prof. Daniel Osei (thesis advisor) | **Monday mornings 10 to 12** only, Room 307 |
| user_02 | Kevin Tran (former manager) | **often reschedules because he's on call** |
| user_03 | Prof. Elena Vasquez | TA meeting **Mondays 9 am**, moved to **Thursday 9 am** when she travels |
| user_03 | Maya Lindqvist (Brightwater, Chicago) | **always two options, in Central time** |
| user_03 | Hannah Cho (alum) | **lunch only, 12 to 1, at Arcadia Café** |
| user_03 | Dr. Samuel Achebe | **his assistant Irene Park schedules** |
| user_04 | Dana Whitfield | **video, Mondays 8 am ET = 1 pm London** (noon the week of Oct 26) |
| user_04 | Rohan Mehta | **in person, Saturday mornings at the Linden café** |
| user_04 | Prof. Ruth Calloway | **Thursdays only; lab manager Owen Fitch schedules** |
| user_04 | Mateo Sandoval (PhD student) | **Friday check-ins, 4 pm London** |

## Shared contacts (isolation test)

Six people write to more than one user, from the same address (so they get the
same `EMAIL_###` placeholder everywhere), but with **different details per user**.
If a search for one user ever returns another user's message, the answer will be
visibly wrong.

| Contact | Users | Differs how |
|---|---|---|
| Dana Whitfield | 01, 02, 04 | Tuesdays in person / Fridays video / Mondays video from London |
| Nadia Brooks (peer coach) | 01, 02 | mock interview in person Tue Oct 6 / Zoom Fri Oct 9 |
| Jordan Lee, Tess Navarro | 01, 02 | banking role: superday Fri Oct 16 / engineering role: final Thu Oct 22 |
| Elena Vasquez | 01, 03 | student office hours / TA meetings |
| Rohan Mehta | 01, 04 | phone calls mornings ET / Saturday coffee in London |

Two mailing-list emails are **word for word identical** across inboxes: the career
center's "Fall recruiting kickoff" (user_01, 02, 04 `t001`) and the STAT 142
announcement (user_01 `t004`, user_03 `t010`). They get a different `message_id`
per user, and ingest keeps every copy.

## Labels

| User | new_request | proposed_times | acceptance | reschedule | assistant_handoff | none | Total |
|---|---|---|---|---|---|---|---|
| user_01 | 17 | 20 | 25 | 10 | 2 | 26 | 100 |
| user_02 | 12 | 20 | 24 | 9 | 4 | 28 | 97 |
| user_03 | 11 | 19 | 27 | 12 | 1 | 20 | 90 |
| user_04 | 11 | 20 | 25 | 10 | 2 | 22 | 90 |
| **all** | **51** | **79** | **101** | **41** | **9** | **96** | **377** |

Labels follow `docs/data/labeling_rules.md` (v1.2). Rules v1.1 corrected 2 labels and v1.2 another 12,
mostly introductions that were `assistant_handoff` and are now `new_request` (E17). The full list
is in PR #14 and [`training_conflicts.md`](training_conflicts.md).

**`needs_response`** (does the user have to reply to move a meeting forward?) is in
`data/source/annotations.jsonl`, one line per message keyed by `user_id`, `thread_id` and
`position`, set under labeling rules v1.2: 109 `true` and 268 `false`.

| User | true | false |
|---|---|---|
| user_01 | 30 | 70 |
| user_02 | 26 | 71 |
| user_03 | 26 | 64 |
| user_04 | 27 | 63 |

About half of the `none` messages are hard negatives that mention dates or times
but aren't scheduling (deadlines, event announcements, auto-confirmations, an
out-of-office reply, a calendar-invite text). A few threads end open, with a
reschedule nobody has answered yet. A real inbox is ~90% non-scheduling, so
classifier scores measured on this corpus will look better than they would on
real mail.

Label rules, including the priority order for mixed messages, are in
[`labeling_rules.md`](labeling_rules.md), the single source of truth for labels.

## Example queries for the retrieval demo

Each answer is supported by the messages listed (`message_id`s from
`data/processed/messages.jsonl`, data-v1). The isolation pairs ask the same
question for two users and must get different answers.

| # | user_id | Query | Expected answer | Supporting messages |
|---|---|---|---|---|
| 1 | user_01 | When and where do I meet my career advisor? | Dana, in person, Tuesdays (3:00/3:30), Wexley Hall Room 214 | `1a61982811036a4a`, `41399146de4c8d5f` |
| 1b | user_02 | *same query* | Dana, by video, Fridays at 11 am | `8dae41b1e5b399ae` |
| 1c | user_04 | *same query* | Dana, Zoom, Monday mornings 8 am ET (1 pm London) | `735da54c1a072886`, `a5c5d849d2382de2` |
| 2 | user_01 | When is my Larkmoor superday? | Friday, October 16 at 9:00 am, New York | `ee745294983ee9d7` |
| 2b | user_02 | When is my Larkmoor final round? | Thursday, October 22, New York | `613772d7c69fa3de` |
| 3 | user_01 | How does Rohan like to meet? | Phone calls only, mornings ET (he's in London) | `4964afa55a4da41d`, `ba1d09c898efec38` |
| 3b | user_04 | *same query* | In person, Saturday mornings at the Linden café | `8ad6bd221e8f12c2`, `5e757711cfd76baa` |
| 4 | user_01 | When was my Larkmoor first round moved to? | Thursday, October 8 at 11:00 am ET (from Wed Oct 7) | `094c5944e8bdda66` |
| 4b | user_02 | When was my Larkmoor first round moved to? | Friday, October 9 at 1:00 pm (from Tue Oct 6) | `365da2cf1add02e3`, `a404c55fa927c66a` |
| 5 | user_02 | When does Professor Osei meet? | Only Monday mornings, 10 to 12, Room 307 | `ce97ef8acd96c8fb`, `494ddc9e63db2032` |
| 6 | user_02 | Who schedules meetings with Tom Haskell? | His assistant, Gwen Liu | `2d2d15910d701afc`, `7ae0f9aeb1b22234` |
| 7 | user_03 | When is the TA meeting when Prof. Vasquez travels? | Moved from Monday to Thursday, 9 am | `c4d57a2016f6ea81`, `298da54872293839` |
| 8 | user_03 | When is my Brightwater final round? | Moved to Monday, October 19, 10:00 am CT | `c729def2406cdc05`, `97a97e587ac5598b` |
| 9 | user_03 | Where does Hannah Cho like to meet? | Lunch, 12 to 1, in person at Arcadia Café | `5f1e7f2afcf240ab` |
| 10 | user_04 | What time is my Oct 26 advising in London time? | 12 noon (UK clocks go back first) | `89d81fb662f62135` |

For a quick automated check: for each query, the expected `message_id`s should be
in that user's top results, and **no result may have another user's `user_id`**.
