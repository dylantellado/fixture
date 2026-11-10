# Retrieval example

- **Query:** When and where do I meet my career advisor?
- **User:** `user_01` (Priya Shah)
- **Collection:** `messages_user_01`
- **Label filter:** none
- **Embedding model:** gemini-embedding-001 (documents RETRIEVAL_DOCUMENT, query RETRIEVAL_QUERY), cosine distance
- **Indexed from:** `<repo>/data/processed/messages.jsonl` (sha256 `542030285fec8bb8d062dfcb7d15e8dd68f631a334953512a84087e501449087`)
- **Indexed at:** 2026-11-09T20:09:48+00:00
- **Command:** `uv run python query.py --user user_01 "When and where do I meet my career advisor?" --k 5 --markdown` (from `src/rag`)

Each result is one message. Score = the message's similarity to the query (1 - cosine distance) averaged with its thread's; higher is closer.

## 1. Advising appointment (score 0.688)

| Sender | Date | Label | Message id | Chunk |
|---|---|---|---|---|
| `Dana Whitfield <EMAIL_023>` | 2026-09-03T14:02:00-04:00 | `proposed_times` | `1a61982811036a4a` | 0 |

```text
Subject: Advising appointment
From: Dana Whitfield
Date: 2026-09-03T14:02:00-04:00
Replying to Priya Shah: Hi Dana, I'm an economics junior recruiting for investment banking summer analyst roles this fall. Could I book a 1:1 advising appointment in the next week or two to go over my resume and recruiting…

Hi Priya,

Lovely to hear from you, and welcome back. I'd be glad to meet. I have two openings next Tuesday, September 8: 3:00 or 3:30 pm Eastern. Either one would be in person, 30 minutes, in my office in Wexley Hall, Room 214 (second floor, at the end of the hall).

If you can, send me your current resume ahead of time so we can spend the meeting on edits instead of reading.

Warmly,
Dana
```

## 2. Advising appointment (score 0.685)

| Sender | Date | Label | Message id | Chunk |
|---|---|---|---|---|
| `Priya Shah <EMAIL_063>` | 2026-09-03T10:14:00-04:00 | `new_request` | `d61309aa7f48aae2` | 0 |

```text
Subject: Advising appointment
From: Priya Shah
Date: 2026-09-03T10:14:00-04:00

Hi Dana,

I'm an economics junior recruiting for investment banking summer analyst roles this fall. Could I book a 1:1 advising appointment in the next week or two to go over my resume and recruiting plan?

Best,
Priya
```

## 3. Fall recruiting kickoff: dates for your calendar (score 0.676)

| Sender | Date | Label | Message id | Chunk |
|---|---|---|---|---|
| `Dana Whitfield <EMAIL_023>` | 2026-09-01T08:30:00-04:00 | `none` | `1901c022a62edc40` | 0 |

```text
Subject: Fall recruiting kickoff: dates for your calendar
From: Dana Whitfield
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

## 4. Advising appointment (score 0.671)

| Sender | Date | Label | Message id | Chunk |
|---|---|---|---|---|
| `Priya Shah <EMAIL_063>` | 2026-09-03T16:40:00-04:00 | `acceptance` | `803ee4e596c6b3f1` | 0 |

```text
Subject: Advising appointment
From: Priya Shah
Date: 2026-09-03T16:40:00-04:00
Replying to Dana Whitfield: Hi Priya, Lovely to hear from you, and welcome back. I'd be glad to meet. I have two openings next Tuesday, September 8: 3:00 or 3:30 pm Eastern. Either one would be in person, 30 minutes, in my…

Hi Dana,

3:00 on Tuesday works well. I'll see you in Room 214, and I'll send my resume over the weekend.

Best,
Priya
```

## 5. Advising appointment after my Superday (score 0.671)

| Sender | Date | Label | Message id | Chunk |
|---|---|---|---|---|
| `Dana Whitfield <EMAIL_023>` | 2026-10-13T11:30:00-04:00 | `proposed_times` | `41399146de4c8d5f` | 0 |

```text
Subject: Advising appointment after my Superday
From: Dana Whitfield
Date: 2026-10-13T11:30:00-04:00
Replying to Priya Shah: Hi Dana, Could I book another advising appointment next week? I'd like to debrief after my Larkmoor Superday and plan the rest of the season. Best, Priya

Hi Priya,

Of course, and good luck on Friday! Next Tuesday, October 20, I have 3:00 or 3:30 pm ET open. As always, that's in person in Wexley Hall, Room 214, for 30 minutes.

Warmly,
Dana
```

