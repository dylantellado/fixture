# classifier_tuning

Tunes the email classifier's `needs_response` by changing its **harness** (instructions, model,
thinking budget, how much of the thread it sees) and its **rules**
([`docs/data/labeling_rules.md`](../../docs/data/labeling_rules.md)), not model weights. Every run is
tracked in Weights & Biases (project `fixture-classifier`), so we always know which harness and
which rules produced which scores.

## What a run records

| In W&B | What |
|---|---|
| Artifact `prod_v1` (type `harness`, or the harness's name) | The harness YAML file, versioned by W&B. Its sha is in the config |
| Artifact `labeling_rules` (type `rules`) | The rules file used, with its version and sha256 |
| Config | harness name and sha, model, location, thinking budget, context window, rules version, sha256 of the rules file and of the rules text actually sent, md5 of every data file read (same hash DVC uses, so it matches `dvc.lock`), split, git commit |
| Summary | `needs_response/accuracy`, `precision`, `recall`, `f1`, `missed` (should answer, predicted no), `false_alarms`; `label/accuracy`; accuracy by source (`v1`, `generated`) and by act (`propose`, `still_on`, ...); tokens; failures |
| Tables | Every prediction (with the reason), and the label confusion table |
| Artifact `report-<harness>` | The run's `report.md` |

A local copy goes to `runs/<harness>-<UTC time>/` (`report.md` is committed; the rest stays local).

## Run

Setup once: `wandb login` (or `WANDB_MODE=offline`, then `wandb sync` later), and
`gcloud auth application-default login` for Gemini on Vertex AI. Data: `dvc pull` from the repo root.

From `experiments/classifier_tuning`:

```sh
uv run python main.py --limit 30 --notes "quick check"                     # prod_v1 harness, train split
uv run python main.py --harness harnesses/prod_v1.yaml --notes "baseline"  # full train split
uv run python main.py --rules ../../docs/data/labeling_rules.md --notes "rules v1.5"
uv run python main.py --split eval --notes "final"                          # held-out users, report only
uv run pytest
```

## How to tune

1. Start from the baseline: a full `train` run of `prod_v1`.
2. Look at the mistakes (W&B predictions table, filter `needs_response != true_needs_response`, or
   `report.md`), grouped by act.
3. Change **one** thing: copy the harness to a new file (`harnesses/<name>.yaml`) and edit it, or
   draft a rules change in a copy of the rules file and pass `--rules`.
4. Run again with `--notes` saying what changed, and compare runs in W&B.
5. Adopt a winner: a rules change goes through `labeling_rules.md` (bump the version, change log,
   re-check affected messages); a harness change goes to `src/classifier` (Dylan's service) in
   its own PR.

Rules for honest numbers:
- Never edit a harness file that already has runs; make a new one. The harness sha is how runs
  are told apart.
- Tune only on `train`. Run `eval` (held-out generated users) only to report a final number, and
  never change anything because of it. eval-v1 (`data/eval/`) is never read here.
