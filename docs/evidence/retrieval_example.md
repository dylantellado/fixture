# Retrieval example

- **Query:** When is my Northbridge interview?
- **User:** `user_01` (Priya Shah)
- **Collection:** `messages_user_01`
- **Label filter:** none
- **Embedding model:** all-MiniLM-L6-v2, cosine distance
- **Indexed from:** `/samples/messages_sample.jsonl` (sha256 `9d2e1829ea57b8d0966a6f38b7571603bd3d50ad823047bf6d2341c1b044d912`)
- **Indexed at:** 2026-10-20T01:20:48+00:00
- **Command:** `uv run python query.py --user user_01 "When is my Northbridge interview?" --k 5 --markdown` (from `src/rag`)

Score = 1 - cosine distance (higher is closer).

> Built from the committed sample data (`samples/`), not generated pipeline data.

## 1. Re: Northbridge Capital first-round interview (score 0.797)

| Sender | Date | Label | Message id | Chunk |
|---|---|---|---|---|
| `Jordan Lee <EMAIL_003>` | 2026-10-13T15:05:00-04:00 | `acceptance` | `0ed574b41b112de0` | 0 |

```text
From: Jordan Lee
Subject: Re: Northbridge Capital first-round interview
Date: 2026-10-13T15:05:00-04:00

Great, let's do Tuesday, October 20 at 2:30 pm Eastern. I'll send a Zoom link the day before. Looking forward to it.
```

## 2. Northbridge Capital first-round interview (score 0.767)

| Sender | Date | Label | Message id | Chunk |
|---|---|---|---|---|
| `Jordan Lee <EMAIL_003>` | 2026-10-13T09:12:00-04:00 | `new_request` | `1901c022a62edc40` | 0 |

```text
From: Jordan Lee
Subject: Northbridge Capital first-round interview
Date: 2026-10-13T09:12:00-04:00

Hi Priya, thanks for applying to the Northbridge Capital summer analyst program. We'd like to schedule a 30-minute first-round video interview with you next week. Could you send a few times that work? You can also reach me at PHONE_001.
```

## 3. Re: Northbridge Capital first-round interview (score 0.716)

| Sender | Date | Label | Message id | Chunk |
|---|---|---|---|---|
| `Priya Shah <EMAIL_001>` | 2026-10-13T11:40:00-04:00 | `proposed_times` | `671eb9711fa3f309` | 0 |

```text
From: Priya Shah
Subject: Re: Northbridge Capital first-round interview
Date: 2026-10-13T11:40:00-04:00

Hi Jordan, thank you! I'm available Tuesday, October 20 from 2:00 to 4:00 pm or Wednesday, October 21 any time after 1:00 pm (Eastern).
```

## 4. Re: CS 1810 final project office hours (score 0.412)

| Sender | Date | Label | Message id | Chunk |
|---|---|---|---|---|
| `Elena Vasquez <EMAIL_004>` | 2026-10-14T13:30:00-04:00 | `assistant_handoff` | `1a61982811036a4a` | 0 |

```text
From: Elena Vasquez
Subject: Re: CS 1810 final project office hours
Date: 2026-10-14T13:30:00-04:00

Hi Priya, happy to meet. I'm copying my assistant Tom Okafor, who manages my calendar and will find a time for us.
```

## 5. Re: CS 1810 final project office hours (score 0.383)

| Sender | Date | Label | Message id | Chunk |
|---|---|---|---|---|
| `Priya Shah <EMAIL_001>` | 2026-10-14T17:45:00-04:00 | `acceptance` | `5262c6e077ade5ff` | 0 |

```text
From: Priya Shah
Subject: Re: CS 1810 final project office hours
Date: 2026-10-14T17:45:00-04:00

Friday, October 23 at 3:00 pm works for me. Thank you, Tom!
```

