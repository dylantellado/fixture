# Labeling rules

**Version 1.2, 2026-10-29.** The single source of truth for the correct answer for every
message: its `label` and its `needs_response`. Any rule change must update this file, bump
the version, add a change log entry, and re-check the messages it affects.

Each rule has an id (`D1`, `E8`, `NR2`, ...). Use the ids when recording why a label or
value was set or changed.

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

## 5. Not adopted (as of v1.2)

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

## 6. Training data (data-v1)

Training labels and `needs_response` follow this file as of v1.2 (PR #14). That PR covers all
377 training messages:

- **Label corrections:** 14 in total.
  - v1.1: `78c903101dc57a53` → `new_request` (E11) and `ffbb97746b68b458` → `reschedule` (E4, T3).
  - v1.2: `dedb6df0524a507a` → `reschedule` (E4, T3), `166482ab09374bcc` → `acceptance` (D3, PR),
    and 10 introductions `assistant_handoff` → `new_request` (E17): `03783fec7a218790`,
    `93f25b0d0032ce69`, `6036baac6f4ce32a`, `9d817cdfb67a8e11`, `2b1bc892af42b94d`,
    `5c59fc9c128c0aaa`, `2674fadcdafd1e36`, `3ba2c3724b1721c5`, `400cd99558be9f06` and
    `7ed0ed3364919fee`.
- **`needs_response`** for every message, in `data/source/annotations.jsonl`: 109 `true` and
  268 `false`.

These `needs_response` values are judgment calls that aren't directive moves, so NR9 doesn't
settle them. They are kept as set:
- `93f25b0d0032ce69`, `03783fec7a218790` and `9ec4921c2af5fb14` (`true`): introductions where
  nobody is named to go first.
- `72837e8226d6398f` (`true`): an interview invitation with no times.
- `43a367a134dde704` (`false`): TAs splitting course sections, which is not a meeting.

## Change log

| Date | Version | What changed | Messages affected |
|---|---|---|---|
| 2026-10-28 | 1.0 | Created this file. Moved D1 to D6, PR and E1 to E7 unchanged from `docs/data/generation/corpus_plan.md`. Added NR1 to NR4, E8 to E12 and T1 to T3. E8 and E9 replace eval v1's earlier "vague pleasantry → none" and "cold sales by intent" decisions. Re-checked all 298 eval v1 messages; training data not changed (section 6). | Eval v1: 16 messages, 18 changes (8 labels, 10 needs_response), listed in `data/eval/v1/README.md` and `data/eval/v1/changes_rules_v1.0.json`. Training: 0 changed, 2 conflicts listed. |
| 2026-10-29 | 1.1 | Adopted P1 as E13 (still on? check-ins: `none`, NR6 `true`), P2 as E14 (restated agreed time: `none`, NR7 `false`), P3 as E15 (label only the new text; quoted agreement doesn't set the label), P5 as E16 (scheduling-link invites: `proposed_times`, NR5 `true`, replacing that part of NR4), P10 as NR8 (catch-ups: `true` from a real person writing personally, `false` from automated or mass mail) and P11 into NR3 (asking the user to send the invite makes it `true`). A message the user sent stays `false` (NR1) whatever the other rules say. P4, P6, P7, P8 and P9 were not adopted. Re-checked all 298 eval v1 messages and all 377 training messages. | Eval v1: 9 messages, 10 changes (2 labels, 8 needs_response), listed in `data/eval/v1/README.md` and `changes_rules_v1.1.json`. Training (PR #14): 2 labels changed, `needs_response` added to all 377 messages. |
| 2026-10-29 | 1.2 | Added E17 (introductions: `new_request` when the person introduced will hold the meeting, `assistant_handoff` when someone coordinates on another person's behalf; decide by what the person will do, not their title) and NR9 (a directive move with no question asked is `true`, but not notices to a mailing list or group address). E16 keeps the broad reading: a booking link sent by a person is also `proposed_times`. P4 is superseded by E17. | Eval v1: 7 messages, 7 changes (4 labels, 3 needs_response), listed in `data/eval/v1/README.md` and `changes_rules_v1.2.json`. Training (PR #14): 12 labels and 1 needs_response. |
