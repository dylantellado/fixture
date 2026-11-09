# RAG experiments

One row per scored run of `check_retrieval.py --record`, appended automatically.
Rows are never edited or removed: they are the history of what each setup scored.
Splits: `dev` is used to build and tune; `test` is only reported (see
`src/rag/retrieval_cases.json` for the seed that drew it). Recall@5 is the share
of expected messages in the top 5; MRR uses the first expected message in the
top 5. "Over limit" counts chunks longer than the embedding model's token limit.

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
