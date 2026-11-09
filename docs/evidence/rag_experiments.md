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
