# Retrieval check

Will's example queries (`docs/data/corpus_notes.md`), each searched in that user's own collection.

- **Command:** `uv run python check_retrieval.py --k 5 --markdown` (from `src/rag`)
- **Embedding model:** all-MiniLM-L6-v2, cosine distance
- **Indexed from:** sha256 `3f9eb1863b9fee1e0e8f0346011f4703680723b7cdf1dbb36b4ffd1840d39a7b`, at 2026-10-20T02:25:39+00:00

## Summary

- **Isolation:** 0 results from another user's mailbox across 15 queries (must be 0).
- **All answering messages in the top 5:** 7 of 15 queries.
- **Some of them:** 4. **None of them:** 4.

A miss usually means search found the right thread but ranked a short reply (for example "I'd like Friday at 9") lower, because one chunk is one message.

## Queries

| # | User | Query | Expected answer | Found | Rank(s) in top 5 | Other users' results |
|---|---|---|---|---|---|---|
| 1 | `user_01` | When and where do I meet my career advisor? | Dana, in person, Tuesdays (3:00/3:30), Wexley Hall Room 214 | 2/2 | 2, 4 | 0 |
| 1b | `user_02` | When and where do I meet my career advisor? | Dana, by video, Fridays at 11 am | 1/1 | 2 | 0 |
| 1c | `user_04` | When and where do I meet my career advisor? | Dana, Zoom, Monday mornings 8 am ET (1 pm London) | 1/2 | 5, – | 0 |
| 2 | `user_01` | When is my Larkmoor superday? | Friday, October 16 at 9:00 am, New York | 0/1 | – | 0 |
| 2b | `user_02` | When is my Larkmoor final round? | Thursday, October 22, New York | 1/1 | 3 | 0 |
| 3 | `user_01` | How does Rohan like to meet? | Phone calls only, mornings ET (he's in London) | 1/2 | –, 1 | 0 |
| 3b | `user_04` | How does Rohan like to meet? | In person, Saturday mornings at the Linden café | 1/2 | 3, – | 0 |
| 4 | `user_01` | When was my Larkmoor first round moved to? | Thursday, October 8 at 11:00 am ET (from Wed Oct 7) | 0/1 | – | 0 |
| 4b | `user_02` | When was my Larkmoor first round moved to? | Friday, October 9 at 1:00 pm (from Tue Oct 6) | 1/2 | –, 5 | 0 |
| 5 | `user_02` | When does Professor Osei meet? | Only Monday mornings, 10 to 12, Room 307 | 2/2 | 3, 1 | 0 |
| 6 | `user_02` | Who schedules meetings with Tom Haskell? | His assistant, Gwen Liu | 2/2 | 2, 5 | 0 |
| 7 | `user_03` | When is the TA meeting when Prof. Vasquez travels? | Moved from Monday to Thursday, 9 am | 2/2 | 3, 2 | 0 |
| 8 | `user_03` | When is my Brightwater final round? | Moved to Monday, October 19, 10:00 am CT | 0/2 | –, – | 0 |
| 9 | `user_03` | Where does Hannah Cho like to meet? | Lunch, 12 to 1, in person at Arcadia Café | 0/1 | – | 0 |
| 10 | `user_04` | What time is my Oct 26 advising in London time? | 12 noon (UK clocks go back first) | 1/1 | 1 | 0 |

Rank `–` means that message wasn't in the top results.
