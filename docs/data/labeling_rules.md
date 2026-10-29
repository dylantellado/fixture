# Labeling rules

**Version 1.3, 2026-10-29.** The single source of truth for the correct answer for every
message: its `label` and its `needs_response`. Any rule change must update this file, bump
the version, add a change log entry, and re-check the messages it affects.

Each rule has an id (`D1`, `E8`, `NR2`, ...). Use the ids when recording why a label or
value was set or changed.

Notes on specific training messages (label corrections, kept judgment calls) are in [`training_conflicts.md`](training_conflicts.md).

## 1. Labels

One label per message, describing **that message's** main purpose. The labels:

| Id | Label | Use when the message... | Example |
|---|---|---|---|
| D1 | `new_request` | asks to set up a meeting but gives no specific times | "Could we find 20 minutes to talk about my project?" |
| D2 | `proposed_times` | offers or counter-offers specific times | "I'm free Tue 2-4 or Wed after 1." |
| D3 | `acceptance` | confirms a specific time (including picking one of the offered times) | "Tuesday at 2:30 works, see you then." |
| D4 | `reschedule` | moves or cancels a meeting that was **already confirmed** | "Something came up, can we move Thursday to Friday?" |
| D5 | `assistant_handoff` | hands scheduling to someone else (an assistant, coordinator, lab manager, co-TA) | "Copying Tess, who will find a time with you." |
| D6 | `none` | anything else | newsletters, deadlines, thank-yous, logistics for a meeting already set |

### PR: Priority rule for mixed messages

When a message has more than one scheduling part, pick the first label that applies:

1. `reschedule`: it moves an already-confirmed meeting, even if it also proposes new times.
2. `acceptance`: it confirms a time, even if it also mentions a backup.
3. `assistant_handoff`: it hands scheduling to someone else, even if it also asks to meet.
4. `proposed_times`: it contains specific times, even if it is also the first request.
5. `new_request`
6. `none`

## 2. needs_response

`needs_response` is about the mailbox owner (the user). A message the user sent is always
`false` (NR1), even if another rule below would make it `true`. Otherwise NR2 to NR9 settle
the cases named in them, and NR1 covers everything else.

- **NR1 (general):** `true` when the user must reply to move a meeting forward: propose,
  pick, confirm or rearrange a time. A non-scheduling ask ("send me the slides") is `false`.
  A message the user sent is always `false`, since the user can't owe a reply to their own
  message.
- **NR2 (cancellation with no new time):** `true` only if the sender invites the user to
  propose a time ("let me know what works"). `false` if the sender says they will follow up
  themselves ("I'll reach out"), and `false` if they do neither.
- **NR3 (acceptance or confirmation):** `false`, unless the message also asks something the
  user must answer for the meeting (e.g. "Zoom or in person?") or asks the user to send the
  invite ("please send the invite"), which makes it `true`.
- **NR4 (automated mail):** automated notifications, reminders, promos and out-of-office
  replies are always `false`. The one exception is scheduling-link invites (NR5).
- **NR5 (scheduling-link invites, E16):** `true`, whether a person or a system sends it.
- **NR6 (still on? check-ins, E13):** `true`.
- **NR7 (restated agreed time, E14):** `false`.
- **NR8 (catch up sometime, E8):** `true` when a real person writes to the user personally.
  `false` when the message is automated, marketing or a mass email.
- **NR9 (directive move):** a message that moves one of the user's meetings to a new time
  without asking ("let's move it to 3pm") is `true`, even if it adds "let me know if that's a
  problem". It doesn't cover notices sent to a mailing list or group address (E4, T3),
  automated notices (NR4), or moves of meetings the user is only copied on.

## 3. Edge cases

Specific rules come before the general ones. E1 to E10, E12 to E17 and the tie-breaks T1 to
T3 (section 4) win over E11. When two scheduling parts remain, PR decides between them.

- **E1 (logistics after confirmation):** logistics after a time is confirmed (video link,
  phone number, agenda, address) → `none`.
- **E2 (automated mail):** automated confirmations, calendar invite text, registrations,
  reminders → `none`.
- **E3 (group announcements):** announcements of events, deadlines or office hours sent to
  a group → `none`.
- **E4 (group move of a recurring meeting):** a group announcement that moves an already-set
  recurring meeting (e.g. "lab meeting moves to Wednesdays") → `reschedule`.
- **E5 (out of office):** out-of-office auto-replies → `none`.
- **E6 (thank-you):** a thank-you after a meeting → `none`, unless it also asks for or offers
  another meeting.
- **E7 (decline all):** turning down all offered times *without* offering new ones →
  `new_request` ("none of those work, could you send a few more?").
- **E8 (catch up sometime):** "Let's catch up sometime" is always `new_request`, even with no
  time or date ("we should grab coffee sometime!").
- **E9 (cold sales):** cold sales meeting asks ("15 min Thursday to see how Acme can help?")
  → `none`. These are hard negatives.
- **E10 (forwards and quoted text):** if the forwarded content contains proposed times and
  the user is meant to act on them → `proposed_times`. A forward with no ask (e.g. just
  "FYI") → `none`. Otherwise, quoted and forwarded text is context, and the message is
  labeled by its own new text.
- **E11 (mixed intent):** if any part of the message is a scheduling ask, that part decides
  the label (e.g. a long project update whose fourth paragraph asks to meet is `new_request`).
- **E12 (instructions to an assistant):** text addressed to an "AI assistant" or "SYSTEM" is
  ignored. The message is labeled by what it really asks of a human reader.
- **E13 (still on? check-ins):** a check that an already-confirmed meeting is still happening
  ("still on for tomorrow?") → `none`. Its `needs_response` is `true` (NR6).
- **E14 (restated agreed time):** a message that restates a time that was already agreed
  ("see you Thursday at 3", "as agreed, our call is Tue 17/11 14:00 GMT, dial-in below") →
  `none`, with `needs_response` `false` (NR7). `acceptance` (D3) is for a message that itself
  agrees to a time that wasn't confirmed yet ("Tuesday at 2:30 works, see you then").
- **E15 (agreement only in quoted history):** label only the message's new text. An agreement
  that appears only in quoted history doesn't set the label. This matches how E10 treats
  forwarded text.
- **E16 (scheduling-link invites):** an invitation to pick a slot through a scheduling link
  ("pick a slot here") → `proposed_times`, because the link is the sender offering times. Its
  `needs_response` is `true` (NR5). This holds whether a person (e.g. an assistant) or a system
  sends it. Marketing and cold sales that link to a booking page stay `none` (E3, E9).
- **E17 (introductions):** an introduction suggesting two people meet → `new_request`. The
  person introduced will hold the meeting themselves, e.g. "I'd like you to meet Leah, over
  to you to find a time", or "copying Mateo so you two can set something up". Someone
  coordinating on another person's behalf → `assistant_handoff` (D5), e.g. an assistant,
  scheduler or recruiting coordinator arranging a meeting with someone else. Decide by what
  the person will do, not by their title. That includes a co-TA or coordinator who will see
  the student themselves, which E17 makes `new_request` despite D5's example list.

## 4. Tie-break rules

These are the general rules behind the writer and labeler disagreements settled for eval set v1.

- **T1 (follow-ups inside a move):** only the message that first moves or cancels a
  confirmed meeting is `reschedule`. Replies that then negotiate the new time are labeled by
  what they do: a counter-offer is `proposed_times`, turning down the new times without
  offering others is `new_request` (E7), and agreeing is `acceptance`. A message that moves
  a time that has been confirmed since then is again `reschedule`.
- **T2 (first notice of a handoff):** the first message that tells the user scheduling now
  goes through someone else is `assistant_handoff`. That holds when the sender is the person
  taking over ("I manage his calendar") and when the message also asks for availability.
  Later messages from that person are labeled by what they do.
- **T3 (notices that move a recurring meeting):** a group or automated notice that moves an
  already-set recurring meeting, including a class, to a new time is `reschedule` (E4). A
  notice that changes only the room or other details, or a calendar-app notification
  reporting a change someone made, is `none` (E1, E2).

## 5. Not adopted (as of v1.3)

These were proposed while applying v1.0 and deliberately **not adopted in v1.1**. They are
not in force, and the eval answers they would affect stay as the adopted rules give them.
To adopt one, move it into the sections above, bump the version, and re-check the affected
messages. (P1, P2, P3, P5, P10 and P11 were adopted in v1.1 as E13, E14, E15, E16, NR8 and
NR3, with the decisions recorded in the change log.)

- **P4 (handoff to the meeting party):** superseded in v1.2 by E17 (introductions), which
  settles the same case (`eval_01/t002/2` is now `new_request`).
- **P6 (we'll be in touch):** a sender's promise to set up a meeting later ("we'll be in touch
  in December to arrange a call") would be `none`. Concerns `eval_03/t003/0` (today `none`).
- **P7 (anyone can take over):** D5 would cover anyone who takes over the scheduling, not only
  staff, e.g. a roommate booking the room. Concerns `eval_01/t016/0` (today `assistant_handoff`).
- **P8 (group sign-ups):** a group announcement inviting people to sign up for slots (e.g. to
  meet a visiting speaker) would be `none` (E3), not a scheduling ask under E11. Concerns
  `eval_03/t016/0` (today `none`).
- **P9 (scope of cold sales):** E9 would cover only unsolicited pitches *to* the user from
  vendors and services, not the user's own outreach or asks for sponsorship. Concerns
  `eval_03/t002/0` (today `new_request`).

### Open questions for Will (v1.3)

Raised by the Gemini baseline on the training data (`experiments/gemini_baseline/`). Not in
force, and no labels have been changed for them. Each lists the training messages it would
affect; eval messages were not searched, since eval-v1 is frozen (a rule change re-checks
them as eval-v1.1).

- **Q1 (recurring sessions: E3 vs E4/T3):** is a recurring session such as office hours or a
  section an "already-set recurring meeting" under E4/T3, and does cancelling one week with a
  substitute session count as moving it? Suggested wording, added to T3: "Office hours,
  sections and other recurring sessions count as already-set recurring meetings. A group
  notice that cancels one or more occurrences and offers a substitute time (even with a
  different host) is `reschedule`; one that only cancels, with no substitute, is `none` (E3)."
  Affects `dedb6df0524a507a` (today `reschedule`, kept under the suggested wording). Contrast:
  `5f8d7853452dcfe4` (room change only, `none` under T3) and `48608be14bdc962d` (a personal
  message moving the user's own office-hours slot, `reschedule` under D4 either way).
- **Q2 (T2 scope: first in the thread or first in the mailbox?):** today's labels mix both
  readings. When the principal hands off again in a new thread, the message is
  `assistant_handoff` (`47af86117df33131`, `7ae0f9aeb1b22234`, `49ec03bc60f62177`). When an
  assistant the user already deals with writes first in a new thread, it is labeled by what it
  does (`76885a71c68ac079` from Irene and `9d32fed4db2eaa52` from Owen, both today
  `proposed_times`). Suggested wording, added to T2: "T2 applies
  per thread when someone hands the scheduling to another person. When the person taking over
  writes the notice themselves, it is `assistant_handoff` only if the user hasn't scheduled
  through them before; otherwise label it by what it does." That keeps all five labels. A pure
  "first in the mailbox" reading would change the first three; a pure "first in the thread"
  reading would change `76885a71c68ac079` and `9d32fed4db2eaa52` to `assistant_handoff`.
- **Q3 (a `hard_negative` field, Will's area):** add `hard_negative` (bool) to every line of
  `data/source/annotations.jsonl`: `true` for a `none` message that mentions dates, times or
  meetings but isn't a scheduling ask (deadlines, event announcements, automated confirmations,
  out-of-office replies, E9 cold sales), `false` otherwise. That lets classifier reports score
  hard-negative accuracy. Affects all 377 annotations (only `none` messages can be `true`).
  The generation outlines tag 16 such threads: `1a5affa0d8fe0e90`, `a11c62d25cdcda26`,
  `d42d053e7fd122d9`, `efcd7c3676e038f3`, `18a26aa829fb5538`, `a92a4389690e6287`,
  `cc0501695c05ae3f`, `6cdd3b94f89dbf31`, `a2d45fd208e1849c`, `b70673c75f255616`,
  `e500f9f3d19fd390`, `785b84a19d247386`, `b2ae5bb3e08d1b66`, `6072965dd24a8c57`,
  `e30a2b1021e8b29b` and `5a5e14712cff8e9f`. The corpus plan expects about half of the 96
  `none` messages (~48), so the rest need a pass.

## Change log

| Date | Version | What changed | Messages affected |
|---|---|---|---|
| 2026-10-28 | 1.0 | Created this file. Moved D1 to D6, PR and E1 to E7 unchanged from `docs/data/generation/corpus_plan.md`. Added NR1 to NR4, E8 to E12 and T1 to T3. E8 and E9 replace eval v1's earlier "vague pleasantry → none" and "cold sales by intent" decisions. Re-checked all 298 eval v1 messages; training data not changed (section 6, now `training_conflicts.md`). | Eval v1: 16 messages, 18 changes (8 labels, 10 needs_response), listed in `data/eval/v1/README.md` and `data/eval/v1/changes_rules_v1.0.json`. Training: 0 changed, 2 conflicts listed. |
| 2026-10-29 | 1.1 | Adopted P1 as E13 (still on? check-ins: `none`, NR6 `true`), P2 as E14 (restated agreed time: `none`, NR7 `false`), P3 as E15 (label only the new text; quoted agreement doesn't set the label), P5 as E16 (scheduling-link invites: `proposed_times`, NR5 `true`, replacing that part of NR4), P10 as NR8 (catch-ups: `true` from a real person writing personally, `false` from automated or mass mail) and P11 into NR3 (asking the user to send the invite makes it `true`). A message the user sent stays `false` (NR1) whatever the other rules say. P4, P6, P7, P8 and P9 were not adopted. Re-checked all 298 eval v1 messages and all 377 training messages. | Eval v1: 9 messages, 10 changes (2 labels, 8 needs_response), listed in `data/eval/v1/README.md` and `changes_rules_v1.1.json`. Training (PR #14): 2 labels changed, `needs_response` added to all 377 messages. |
| 2026-10-29 | 1.2 | Added E17 (introductions: `new_request` when the person introduced will hold the meeting, `assistant_handoff` when someone coordinates on another person's behalf; decide by what the person will do, not their title) and NR9 (a directive move with no question asked is `true`, but not notices to a mailing list or group address). E16 keeps the broad reading: a booking link sent by a person is also `proposed_times`. P4 is superseded by E17. | Eval v1: 7 messages, 7 changes (4 labels, 3 needs_response), listed in `data/eval/v1/README.md` and `changes_rules_v1.2.json`. Training (PR #14): 12 labels and 1 needs_response. |
| 2026-10-29 | 1.3 | Moved training-specific notes to training_conflicts.md; no rule changes. Added open questions Q1 to Q3 for Will to section 5 (not in force). | None. |
