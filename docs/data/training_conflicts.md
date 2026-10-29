# Training data notes (data-v1)

Moved unchanged from section 6 of [`labeling_rules.md`](labeling_rules.md) in rules v1.3, so
notes about specific training messages stay out of the rules (and out of any prompt built
from them). Below, "this file" means `labeling_rules.md`.

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
