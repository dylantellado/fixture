# Training data notes (data-v1)

Moved unchanged from section 6 of [`labeling_rules.md`](labeling_rules.md) in rules v1.3, so
notes about specific training messages stay out of the rules (and out of any prompt built
from them). In the section moved from the rules, "this file" means `labeling_rules.md`.
Changes from later rule versions are added at the end.

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

## Rules v1.4 (PR #15)

All 377 training messages were re-checked against v1.4, and `rules_version` is now `1.4` on
every line of `data/source/annotations.jsonl`. Each new or changed rule was checked against
every message it could reach: every user acceptance and the other person's next message (E20,
E14); every `assistant_handoff` and every first message from a person who schedules for
someone else (T2); every introduction (NR10); every cancelled or moved recurring session
(E18); and every message that divides work (E19).

**7 label changes**, no `needs_response` changes:

| message_id | user / thread / position | field | old → new | rule |
|---|---|---|---|---|
| `b5915cbaa6429823` | user_01 / t007 / 3 | label | `none` → `acceptance` | E20: "Brilliant, Monday it is" after Priya picked Monday of two options |
| `b227ffa15979d941` | user_01 / t019 / 4 | label | `none` → `acceptance` | E20: "You're confirmed for Wednesday, October 7 at 2:00 pm" after Priya picked one of three |
| `33b6748257976b14` | user_02 / t020 / 4 | label | `none` → `acceptance` | E20: "You're confirmed for Tuesday, October 6" after Marcus picked one of three |
| `1721f289b5589cf4` | user_02 / t027 / 3 | label | `none` → `acceptance` | E20: "You're all set for Tuesday, October 13" after Marcus picked one of two |
| `47af86117df33131` | user_01 / t025 / 0 | label | `assistant_handoff` → `new_request` | T2: Tess was already introduced as the scheduler in t019; Superday invite, no times (D1) |
| `7ae0f9aeb1b22234` | user_02 / t027 / 0 | label | `assistant_handoff` → `new_request` | T2: Gwen was already introduced in t011; final-round invite, no times (D1) |
| `49ec03bc60f62177` | user_02 / t032 / 0 | label | `assistant_handoff` → `new_request` | T2: Tess was already introduced in t020; final-round invite, no times (D1) |

For the four E20 messages, `needs_response` stays `false`, now under NR3 instead of NR7: none
asks something the user must answer. Their `rule` field changes from `NR7` to `NR3`.

Kept as they were (judgment calls under v1.4):
- `43ae86614c62dbf8`, `357e1592bdc3154a` and `9b7b6dd8e4108416` stay `none`: the other person
  offered a single time and the user accepted it, so the user's acceptance confirmed it, and
  the reply restates it (E14). E20 is read as applying only when the user chose the time
  (picked one of several, or proposed it).
- `166482ab09374bcc` ("Friday it is!") was already `acceptance`, which E20 now states.
- `dedb6df0524a507a` was already `reschedule`, which E18 now states.
- `b69c3b5f0b813da8`, `43a367a134dde704` (section split) and `83bdf51558a03119` (grading split)
  were already `none`, which E19 now states.
- `76885a71c68ac079` (Irene) and `9d32fed4db2eaa52` (Owen) stay `proposed_times`: each person
  was already the user's scheduler from an earlier thread (T2).
- `ad42df6a18e6b6d7` stays `assistant_handoff`: it is the first notice that scheduling the lab
  meeting goes through Mateo. T2 counts the first notice per person taking over, not only the
  first handoff of any kind in the mailbox.
- Every introduction already follows NR10, including `2b1bc892af42b94d` (`false`: Grace is
  asked to arrange it) and `93f25b0d0032ce69`, `03783fec7a218790` and `9ec4921c2af5fb14`
  (`true`: the introducer leaves both people to find a time).

Counts after v1.4: acceptance 105, none 92, proposed_times 79, new_request 54, reschedule 41,
assistant_handoff 6; `needs_response` 109 `true` and 268 `false`.
