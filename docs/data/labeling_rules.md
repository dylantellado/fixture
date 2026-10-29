# Labeling rules

**Version 1.0, 2026-10-28.** The single source of truth for the correct answer for every
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

`needs_response` is about the mailbox owner (the user). Rules NR2 to NR4 settle the cases
named in them, and NR1 covers everything else.

- **NR1 (general):** `true` when the user must reply to move a meeting forward: propose,
  pick, confirm or rearrange a time. A non-scheduling ask ("send me the slides") is `false`.
  A message the user sent is always `false`, since the user can't owe a reply to their own
  message.
- **NR2 (cancellation with no new time):** `true` only if the sender invites the user to
  propose a time ("let me know what works"). `false` if the sender says they will follow up
  themselves ("I'll reach out"), and `false` if they do neither.
- **NR3 (acceptance or confirmation):** `false`, unless the message also asks something the
  user must answer for the meeting (e.g. "Zoom or in person?").
- **NR4 (automated mail):** automated notifications, reminders, promos and out-of-office
  replies are always `false`.

## 3. Edge cases

Specific rules come before the general ones. E1 to E10 and the tie-breaks T1 to T3 (section 4)
win over E11. When two scheduling parts remain, PR decides between them.

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

## 5. Proposed (not yet adopted)

Gaps found while applying the rules. **These are not in force.** Messages they would
affect keep the labels the adopted rules give. To adopt one, move it into the sections
above, bump the version, and re-check the affected messages.

- **P1 (still on? checks):** "Just checking we're still on for Thursday at 3?" about an
  already-confirmed meeting → `none` (E1). Under NR1 its `needs_response` is `true`, because
  the user must confirm the time.
- **P2 (restated agreed time):** a message that restates a time already agreed, with logistics
  or a time-zone conversion ("as agreed, our call is Tue 17/11 14:00 GMT, dial-in below") →
  `none`. `acceptance` is only for a message that itself agrees to a time not yet confirmed.
- **P3 (earlier agreement only in quotes):** when the agreement on a time appears only in
  quoted history, not in an earlier message of the thread, the quote counts as evidence that
  the meeting is already confirmed (for D4, T1 and E1).
- **P4 (handoff to the meeting party):** asking a colleague to set up a meeting between
  *that colleague* and the user is `new_request` (the colleague isn't scheduling for someone
  else). D5 applies only when the person taking over arranges the meeting for someone else.
  This would affect `eval_01/t002/2`.
- **P5 (scheduling links from a system):** a personal invitation to book a slot through a
  scheduling link is `new_request`, even when sent by a system. Its `needs_response` would be
  `true`, which overrides NR4 (today such a message is automated, so `false`). This would
  affect `eval_02/t004/0`.
- **P6 (we'll be in touch):** a sender's promise to set up a meeting later ("we'll be in
  touch in December to arrange a call") → `none`. It isn't an ask to the user, and E8 doesn't
  cover it. This would confirm `eval_03/t003/0`.
- **P7 (anyone can take over):** D5 covers anyone who takes over the scheduling, not only
  staff, e.g. a roommate booking the room. This would confirm `eval_01/t016/0`.
- **P8 (group sign-ups):** an announcement sent to a group that invites people to sign up
  for slots (e.g. to meet a visiting speaker) is `none` (E3), not a scheduling ask under E11.
  This would confirm `eval_03/t016/0`.
- **P9 (scope of cold sales):** E9 covers unsolicited pitches *to* the user from vendors
  and services. It doesn't cover the user's own outreach, or asks for sponsorship or funding,
  which keep their scheduling label. This would confirm `eval_03/t002/0` (Noor asking a
  company for a sponsorship call, `new_request`).
- **P10 (needs_response for E8):** a vague catch-up (E8) is `needs_response: true` only if it
  is the main point of the message and waits on the user's answer now. It is `false` when
  it is an aside to a holding reply or explicitly put off to a later period. This would
  confirm `eval_01/t028/2` and `eval_02/t032/2` (`false`) and `eval_01/t015/1` and
  `eval_02/t032/0` (`true`).
- **P11 (tasks inside a confirmation):** under NR3, a request to *do* something for the
  meeting ("please send the invite", "forward the link") is not a question the user must
  answer, so it stays `false`. A question about the meeting itself ("phone or video?",
  "what number should he call?") makes it `true`. This would confirm `eval_03/t005/1`,
  `eval_03/t010/3` and `eval_03/t019/2` (`false`) and `eval_02/t012/2` (`true`).

## 6. Training data conflicts (data-v1, not changed)

These training messages conflict with this file. They are listed for a separate decision,
and `data/source/` is unchanged. Training data has no `needs_response` field, so only labels
were checked (all 377 messages).

| message_id | Message | Current label | Label under these rules | Rule |
|---|---|---|---|---|
| `78c903101dc57a53` | user_03/t019/0: Sofia forwards case-prep notes and asks Clara to do practice cases this week | `none` | `new_request` | E11 (E10: the forwarded notes have no times) |
| `ffbb97746b68b458` | user_04/t011/0: the study-abroad office moves two recurring classes to new times | `none` | `reschedule` | E4, T3 |

Borderline, not counted as a conflict: `dedb6df0524a507a` (user_01/t024/0, `assistant_handoff`).
It's a group email saying office hours are cancelled this week and the TA covers them, with
students booking with him. D5 and T2 allow the current label, but E3 or E4 could be argued.

## Change log

| Date | Version | What changed | Messages affected |
|---|---|---|---|
| 2026-10-28 | 1.0 | Created this file. Moved D1 to D6, PR and E1 to E7 unchanged from `docs/data/generation/corpus_plan.md`. Added NR1 to NR4, E8 to E12 and T1 to T3. E8 and E9 replace eval v1's earlier "vague pleasantry → none" and "cold sales by intent" decisions. Re-checked all 298 eval v1 messages; training data not changed (section 6). | Eval v1: 16 messages, 18 changes (8 labels, 10 needs_response), listed in `data/eval/v1/README.md` and `data/eval/v1/changes_rules_v1.0.json`. Training: 0 changed, 2 conflicts listed. |
