# Retrieval check

47 example queries, each searched in that user's own collection. The first 15 are Will's queries from `docs/data/corpus_notes.md`; the rest were added in Milestone 3 (`src/rag/retrieval_cases.json`). Each lists the messages that answer it.

- **Command:** `uv run python check_retrieval.py --split all --k 5 --markdown` (from `src/rag`)
- **Embedding model:** gemini-embedding-001 (3072 dimensions; documents RETRIEVAL_DOCUMENT, queries RETRIEVAL_QUERY), cosine distance
- **Chunks:** 537 in the searched users' collections, 0 over the model's token limit
- **Indexed from:** sha256 `542030285fec8bb8d062dfcb7d15e8dd68f631a334953512a84087e501449087`, at 2026-11-09T20:09:48+00:00
- **Code:** commit `4379eb1`

## Summary

| Split | Queries | Recall@5 | MRR | Full | Partial | Miss | Cross-user results |
|---|---|---|---|---|---|---|---|
| dev | 32 | 0.883 | 0.672 | 25 | 7 | 0 | 0 |
| test | 15 | 0.800 | 0.716 | 10 | 4 | 1 | 0 |

Cross-user results must be 0: a search never returns another user's messages. `dev` cases were used to build the search; `test` cases were drawn at random before any experiment and never tuned on.

## The 15 original queries: Milestone 2 vs now

Will's example queries from `docs/data/corpus_notes.md`. Milestone 2 used all-MiniLM-L6-v2 with one chunk per message; found/expected and ranks in the top 5.

| # | Split | User | Query | Milestone 2 | Now | Rank(s) now |
|---|---|---|---|---|---|---|
| 1 | dev | `user_01` | When and where do I meet my career advisor? | 2/2 (2, 4) | 2/2 | 1, 5 |
| 1b | test | `user_02` | When and where do I meet my career advisor? | 1/1 (2) | 1/1 | 2 |
| 1c | dev | `user_04` | When and where do I meet my career advisor? | 1/2 (5, –) | 1/2 | 3, – |
| 2 | dev | `user_01` | When is my Larkmoor superday? | 0/1 (–) | 1/1 | 4 |
| 2b | test | `user_02` | When is my Larkmoor final round? | 1/1 (3) | 1/1 | 2 |
| 3 | test | `user_01` | How does Rohan like to meet? | 1/2 (–, 1) | 1/2 | 1, – |
| 3b | test | `user_04` | How does Rohan like to meet? | 1/2 (3, –) | 1/2 | 1, – |
| 4 | dev | `user_01` | When was my Larkmoor first round moved to? | 0/1 (–) | 1/1 | 1 |
| 4b | dev | `user_02` | When was my Larkmoor first round moved to? | 1/2 (–, 5) | 1/2 | 3, – |
| 5 | dev | `user_02` | When does Professor Osei meet? | 2/2 (3, 1) | 2/2 | 1, 3 |
| 6 | test | `user_02` | Who schedules meetings with Tom Haskell? | 2/2 (2, 5) | 1/2 | 1, – |
| 7 | dev | `user_03` | When is the TA meeting when Prof. Vasquez travels? | 2/2 (3, 2) | 2/2 | 1, 2 |
| 8 | dev | `user_03` | When is my Brightwater final round? | 0/2 (–, –) | 1/2 | 4, – |
| 9 | dev | `user_03` | Where does Hannah Cho like to meet? | 0/1 (–) | 1/1 | 1 |
| 10 | test | `user_04` | What time is my Oct 26 advising in London time? | 1/1 (1) | 1/1 | 5 |

## All queries

| # | Split | User | Query | Expected answer | Found | Rank(s) in top 5 | Other users' results |
|---|---|---|---|---|---|---|---|
| 1 | dev | `user_01` | When and where do I meet my career advisor? | Dana, in person, Tuesdays (3:00/3:30), Wexley Hall Room 214 | 2/2 | 1, 5 | 0 |
| 1b | test | `user_02` | When and where do I meet my career advisor? | Dana, by video, Fridays at 11 am | 1/1 | 2 | 0 |
| 1c | dev | `user_04` | When and where do I meet my career advisor? | Dana, Zoom, Monday mornings 8 am ET (1 pm London) | 1/2 | 3, – | 0 |
| 2 | dev | `user_01` | When is my Larkmoor superday? | Friday, October 16 at 9:00 am, New York | 1/1 | 4 | 0 |
| 2b | test | `user_02` | When is my Larkmoor final round? | Thursday, October 22, New York | 1/1 | 2 | 0 |
| 3 | test | `user_01` | How does Rohan like to meet? | Phone calls only, mornings ET (he's in London) | 1/2 | 1, – | 0 |
| 3b | test | `user_04` | How does Rohan like to meet? | In person, Saturday mornings at the Linden café | 1/2 | 1, – | 0 |
| 4 | dev | `user_01` | When was my Larkmoor first round moved to? | Thursday, October 8 at 11:00 am ET (from Wed Oct 7) | 1/1 | 1 | 0 |
| 4b | dev | `user_02` | When was my Larkmoor first round moved to? | Friday, October 9 at 1:00 pm (from Tue Oct 6) | 1/2 | 3, – | 0 |
| 5 | dev | `user_02` | When does Professor Osei meet? | Only Monday mornings, 10 to 12, Room 307 | 2/2 | 1, 3 | 0 |
| 6 | test | `user_02` | Who schedules meetings with Tom Haskell? | His assistant, Gwen Liu | 1/2 | 1, – | 0 |
| 7 | dev | `user_03` | When is the TA meeting when Prof. Vasquez travels? | Moved from Monday to Thursday, 9 am | 2/2 | 1, 2 | 0 |
| 8 | dev | `user_03` | When is my Brightwater final round? | Moved to Monday, October 19, 10:00 am CT | 1/2 | 4, – | 0 |
| 9 | dev | `user_03` | Where does Hannah Cho like to meet? | Lunch, 12 to 1, in person at Arcadia Café | 1/1 | 1 | 0 |
| 10 | test | `user_04` | What time is my Oct 26 advising in London time? | 12 noon (UK clocks go back first) | 1/1 | 5 | 0 |
| n01 | test | `user_01` | Where am I meeting Ada to plan the pitch event? | Copper Kettle, Friday Oct 2 at 10 am (moved from Thursday Oct 1) | 2/2 | 1, 4 | 0 |
| n02 | test | `user_01` | What time is dinner with Maya on Saturday? | 8 pm (pushed from 7) at the Thai place on Elm | 2/2 | 2, 1 | 0 |
| n03 | dev | `user_01` | When did Claire move my October mentor call to? | Sunday, Oct 25 at 7 pm ET (from Oct 18) | 2/2 | 1, 2 | 0 |
| n04 | test | `user_01` | Who covers Professor Vasquez's office hours while she's at a conference? | Theo Marsh: Wednesday Oct 7, 5-6 pm, Science Annex 309 | 1/1 | 1 | 0 |
| n05 | dev | `user_01` | When is my coffee with Rohan in Boston now? | Tuesday, Nov 10 at 8 am at Copper Kettle (moved from Monday Nov 9) | 2/2 | 1, 2 | 0 |
| n06 | dev | `user_01` | What time in London is my first call with Rohan? | 1:30 pm London (Monday Sep 14, 8:30 am ET) | 1/2 | 2, – | 0 |
| n07 | test | `user_01` | When is my mock interview with Nadia before Larkmoor? | Tuesday, Oct 6 at 3:30 pm, in person in Wexley 214 | 2/2 | 1, 2 | 0 |
| n08 | dev | `user_02` | When did Gwen move my call with Tom Haskell to? | Monday, Sep 28 at 3 pm ET (from Wednesday Sep 23) | 2/2 | 1, 2 | 0 |
| n09 | dev | `user_02` | When is my Pinecrest final round? | Tuesday, Oct 13, 12-3 pm ET, by video | 3/3 | 3, 2, 5 | 0 |
| n10 | test | `user_02` | When is my call with Kevin about choosing between offers? | Wednesday, Oct 14 at 6 pm PT / 9 pm ET (moved from Tuesday; he's on call) | 1/2 | 5, – | 0 |
| n11 | dev | `user_02` | What time is the library study session with Sam tonight? | 9 pm (pushed from 8), library 3rd floor, the big table by the windows | 3/3 | 1, 3, 4 | 0 |
| n12 | dev | `user_02` | What time is hackathon prep with Sam on Saturday? | 2 pm (moved from 10 am) | 2/2 | 3, 4 | 0 |
| n13 | dev | `user_02` | Who can help me negotiate my Pinecrest offer, and when do we meet? | Grace Kim, the offers specialist: Friday Oct 16 at 11 am ET on Zoom | 2/2 | 2, 3 | 0 |
| n14 | dev | `user_02` | When is Aisha free for calls? | Wednesday or Friday afternoons Pacific, by video | 1/2 | 1, – | 0 |
| n15 | dev | `user_03` | When am I grading quizzes with Alex? | Saturday, Sep 19 at 11 am in the TA room (moved twice) | 2/2 | 3, 5 | 0 |
| n16 | dev | `user_03` | When is my second lunch with Hannah? | Thursday, Oct 1 at noon at Arcadia Café | 1/2 | 1, – | 0 |
| n17 | dev | `user_03` | When is my debrief lunch with Hannah after the final round? | Thursday, Oct 22 at noon at Arcadia (moved from Wednesday Oct 21) | 2/2 | 4, 5 | 0 |
| n18 | dev | `user_03` | Who schedules my meetings with Dr. Achebe? | His assistant, Irene Park | 2/2 | 3, 2 | 0 |
| n19 | dev | `user_03` | When did my October 9 meeting with Dr. Achebe move to? | Monday, Oct 12, 2:00-2:45 pm, Room 402 | 2/2 | 1, 3 | 0 |
| n20 | test | `user_03` | What time is my round 2 interview with Arjun in Eastern time? | Thursday, Oct 8 at 8:30 am ET (6 pm IST) | 2/2 | 1, 2 | 0 |
| n21 | dev | `user_03` | What time is Mummy's birthday call in Boston time? | Saturday at 11 am (4 pm Lagos), moved from 9 am | 2/2 | 4, 3 | 0 |
| n22 | dev | `user_03` | Who handles travel for my Brightwater final round? | Dev Shah, Brightwater's recruiting coordinator | 1/1 | 2 | 0 |
| n23 | dev | `user_04` | Who schedules meetings with Professor Calloway? | Her lab manager, Owen Fitch (she meets students on Thursdays) | 1/1 | 2 | 0 |
| n24 | dev | `user_04` | When did my October check-in with Ruth move to? | Thursday, Oct 15 at 10 am ET on Zoom (from Oct 8) | 2/2 | 1, 2 | 0 |
| n25 | dev | `user_04` | What time in London is my lab meeting presentation on October 22? | 4 pm London (11 am ET, moved from 10:30) | 1/2 | –, 2 | 0 |
| n26 | test | `user_04` | What time is Sunday's video call with Mama? | 19:00 Berlin / 18:00 London (moved from 18:00 Berlin) | 2/2 | 3, 4 | 0 |
| n27 | dev | `user_04` | When is my check-in with Mateo instead of Friday, October 9? | Thursday, Oct 8 at 4 pm London (11 am ET) | 2/2 | 4, 5 | 0 |
| n28 | test | `user_04` | When is my mid-term feedback meeting with Callum? | Tuesday, Oct 20 at 14:00, room 3.08 | 2/2 | 1, 4 | 0 |
| n29 | dev | `user_04` | When is my follow-up call with Jonas? | Wednesday, Oct 7, 19:00 Berlin / 18:00 London (moved from Tuesday) | 2/2 | 3, 5 | 0 |
| n30 | dev | `user_04` | Where am I meeting Hugo for lunch? | His office lobby, Wednesday Oct 14 at 12:30 | 2/2 | 1, 2 | 0 |
| n31 | dev | `user_04` | What time is the summer fellowship deadline in London time? | 4:59 am Monday, Nov 2 in London (11:59 pm EST, Sunday Nov 1) | 1/1 | 1 | 0 |
| n32 | test | `user_04` | When does Mateo usually do check-ins? | Fridays, 11 am ET / 4 pm London, on Zoom | 0/1 | – | 0 |

Rank `–` means that message wasn't in the top results.

## Experiments

Every scored setup, from `docs/evidence/rag_experiments.md` (rows 1-4 on both splits; ablations on dev only).

| Variant | Embedding model | Split | Queries | Recall@5 | MRR | Full | Partial | Miss | Cross-user | Chunks | Over limit | Commit | Date |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1. Baseline: MiniLM, one chunk per message | all-MiniLM-L6-v2 | dev | 32 | 0.650 | 0.465 | 14 | 12 | 6 | 0 | 390 | 13 | `456b89b` | 2026-11-09 |
| 1. Baseline: MiniLM, one chunk per message | all-MiniLM-L6-v2 | test | 15 | 0.840 | 0.733 | 11 | 4 | 0 | 0 | 390 | 13 | `456b89b` | 2026-11-09 |
| dev ablation: MiniLM + thread context, thread weight 0 | all-MiniLM-L6-v2 | dev | 32 | 0.667 | 0.590 | 17 | 9 | 6 | 0 | 667 | 1 | `29de105` | 2026-11-09 |
| dev ablation: MiniLM + thread context, thread weight 0.5 | all-MiniLM-L6-v2 | dev | 32 | 0.667 | 0.598 | 16 | 11 | 5 | 0 | 667 | 1 | `29de105` | 2026-11-09 |
| 2. MiniLM + thread context | all-MiniLM-L6-v2 | dev | 32 | 0.667 | 0.598 | 16 | 11 | 5 | 0 | 667 | 1 | `29de105` | 2026-11-09 |
| 2. MiniLM + thread context | all-MiniLM-L6-v2 | test | 15 | 0.800 | 0.528 | 11 | 2 | 2 | 0 | 667 | 1 | `29de105` | 2026-11-09 |
| 3. Vertex, one chunk per message | gemini-embedding-001 | dev | 32 | 0.800 | 0.676 | 21 | 10 | 1 | 0 | 377 | 0 | `e82c582` | 2026-11-09 |
| 3. Vertex, one chunk per message | gemini-embedding-001 | test | 15 | 0.840 | 0.761 | 11 | 4 | 0 | 0 | 377 | 0 | `e82c582` | 2026-11-09 |
| dev ablation: Vertex + thread context (one window per thread), thread weight 0 | gemini-embedding-001 | dev | 32 | 0.867 | 0.644 | 25 | 6 | 1 | 0 | 537 | 0 | `e82c582` | 2026-11-09 |
| dev ablation: Vertex + thread context (one window per thread), thread weight 0.5 | gemini-embedding-001 | dev | 32 | 0.883 | 0.672 | 25 | 7 | 0 | 0 | 537 | 0 | `e82c582` | 2026-11-09 |
| dev ablation: Vertex + thread context, windows of 800 characters, thread weight 0.5 | gemini-embedding-001 | dev | 32 | 0.883 | 0.688 | 26 | 5 | 1 | 0 | 606 | 0 | `e82c582-dirty` | 2026-11-09 |
| 4. Vertex + thread context | gemini-embedding-001 | dev | 32 | 0.883 | 0.672 | 25 | 7 | 0 | 0 | 537 | 0 | `d798518` | 2026-11-09 |
| 4. Vertex + thread context | gemini-embedding-001 | test | 15 | 0.800 | 0.716 | 10 | 4 | 1 | 0 | 537 | 0 | `d798518` | 2026-11-09 |
