"""Tests for the pipeline definition and the trigger. Nothing is submitted."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "trigger"))

import pipeline  # noqa: E402
from main import inputs_for  # noqa: E402  (trigger/main.py)


def test_pipeline_compiles_with_four_steps_in_order(tmp_path):
    out = tmp_path / "p.json"
    pipeline.main(["compile", "--data-image", "img/data:1", "--tuning-image", "img/tuning:1", "--out", str(out)])
    spec = json.loads(out.read_text())
    tasks = spec["root"]["dag"]["tasks"]
    assert set(tasks) == {"assemble", "ingest", "preprocess", "evaluate"}
    assert tasks["ingest"]["dependentTasks"] == ["assemble"]
    assert tasks["preprocess"]["dependentTasks"] == ["ingest"]
    assert tasks["evaluate"]["dependentTasks"] == ["preprocess"]
    executors = spec["deploymentSpec"]["executors"]
    assert executors["exec-evaluate"]["container"]["image"] == "img/tuning:1"
    assert executors["exec-ingest"]["container"]["image"] == "img/data:1"
    env = {e["name"] for e in executors["exec-evaluate"]["container"]["env"]}
    assert {"WANDB_API_KEY_SECRET", "WANDB_BASE_URL"} <= env


def test_trigger_reacts_only_to_ready_markers():
    assert inputs_for("b", "pipeline-inputs/abc-def/READY") == "gs://b/pipeline-inputs/abc-def"
    for name in ("pipeline-inputs/abc/UPLOADED", "pipeline-inputs/abc/base/users.json", "dvcstore/files/md5/ab/cd",
                 "pipeline-runs/x/data/source/READY", "pipeline-inputs//READY"):
        assert inputs_for("b", name) is None
