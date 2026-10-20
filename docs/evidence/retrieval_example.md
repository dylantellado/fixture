# Retrieval example

- **Query:** When and where do I meet my career advisor?
- **User:** `user_01` (Priya Shah)
- **Collection:** `messages_user_01`
- **Label filter:** none
- **Embedding model:** all-MiniLM-L6-v2, cosine distance
- **Indexed from:** `/Users/dylantellado/fixture-project/fixture-app/data/processed/messages.jsonl` (sha256 `3f9eb1863b9fee1e0e8f0346011f4703680723b7cdf1dbb36b4ffd1840d39a7b`)
- **Indexed at:** 2026-10-20T02:03:05+00:00
- **Command:** `uv run python query.py --user user_01 "When and where do I meet my career advisor?" --k 5 --markdown` (from `src/rag`)

Score = 1 - cosine distance (higher is closer).

## 1. Fall recruiting kickoff: dates for your calendar (score 0.536)

| Sender | Date | Label | Message id | Chunk |
|---|---|---|---|---|
| `Dana Whitfield <EMAIL_023>` | 2026-09-01T08:30:00-04:00 | `none` | `1901c022a62edc40` | 0 |

```text
From: Dana Whitfield
Subject: Fall recruiting kickoff: dates for your calendar
Date: 2026-09-01T08:30:00-04:00

Hi everyone,

Welcome back! Fall recruiting moves fast, so here are the dates to put in your calendar now:

* Resume workshop: Thu Sep 10, 4:00-5:00 pm, Wexley Hall 120
* Career Fair: Thu Sep 24, 1:00-4:00 pm, Wexley Hall (register online by Sep 21)
* Interview prep night: Tue Oct 6, 6:00 pm, virtual

Drop-in advising runs Monday to Thursday, 1:00-3:00 pm, no appointment needed.
For a 1:1 appointment, just reply to me or call the front desk at PHONE_008.

Studying abroad this term? All of our workshops are recorded, and advisors can
meet by video. Mention your time zone when you write.

Wishing you a great start to the semester,
```

## 2. Advising appointment (score 0.511)

| Sender | Date | Label | Message id | Chunk |
|---|---|---|---|---|
| `Dana Whitfield <EMAIL_023>` | 2026-09-03T14:02:00-04:00 | `proposed_times` | `1a61982811036a4a` | 0 |

```text
From: Dana Whitfield
Subject: Advising appointment
Date: 2026-09-03T14:02:00-04:00

Hi Priya,

Lovely to hear from you, and welcome back. I'd be glad to meet. I have two openings next Tuesday, September 8: 3:00 or 3:30 pm Eastern. Either one would be in person, 30 minutes, in my office in Wexley Hall, Room 214 (second floor, at the end of the hall).

If you can, send me your current resume ahead of time so we can spend the meeting on edits instead of reading.

Warmly,
Dana
```

## 3. Advising appointment (score 0.486)

| Sender | Date | Label | Message id | Chunk |
|---|---|---|---|---|
| `Priya Shah <EMAIL_063>` | 2026-09-03T16:40:00-04:00 | `acceptance` | `803ee4e596c6b3f1` | 0 |

```text
From: Priya Shah
Subject: Advising appointment
Date: 2026-09-03T16:40:00-04:00

Hi Dana,

3:00 on Tuesday works well. I'll see you in Room 214, and I'll send my resume over the weekend.

Best,
Priya
```

## 4. Advising appointment after my Superday (score 0.479)

| Sender | Date | Label | Message id | Chunk |
|---|---|---|---|---|
| `Dana Whitfield <EMAIL_023>` | 2026-10-13T11:30:00-04:00 | `proposed_times` | `41399146de4c8d5f` | 0 |

```text
From: Dana Whitfield
Subject: Advising appointment after my Superday
Date: 2026-10-13T11:30:00-04:00

Hi Priya,

Of course, and good luck on Friday! Next Tuesday, October 20, I have 3:00 or 3:30 pm ET open. As always, that's in person in Wexley Hall, Room 214, for 30 minutes.

Warmly,
Dana
```

## 5. Advising appointment after my Superday (score 0.424)

| Sender | Date | Label | Message id | Chunk |
|---|---|---|---|---|
| `Priya Shah <EMAIL_063>` | 2026-10-13T12:10:00-04:00 | `acceptance` | `0b7d1006908fee16` | 0 |

```text
From: Priya Shah
Subject: Advising appointment after my Superday
Date: 2026-10-13T12:10:00-04:00

Hi Dana,

3:00 on the 20th, please. Thank you.

Best,
Priya
```

