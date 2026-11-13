"""Cloud Function: start the pipeline when a new data version lands in the DVC bucket.

run_pipeline.sh (or anything else) uploads a data version to
gs://<bucket>/pipeline-inputs/<id>/{base,generated}/ and writes <id>/READY last.
That READY object fires this function, which submits the latest compiled
pipeline (pipeline-templates/latest.json) on that folder. Every other object
written to the bucket (DVC's own files, run outputs) is ignored.
"""

import os
from datetime import datetime, timezone

import functions_framework

PROJECT_ID = os.environ.get("PROJECT_ID", "fixture-ac215-96dhbm")
REGION = os.environ.get("REGION", "us-east1")
SERVICE_ACCOUNT = os.environ.get("JOB_SA", f"fixture-tuning@{PROJECT_ID}.iam.gserviceaccount.com")
HARNESS = os.environ.get("HARNESS", "harnesses/prod_v1.yaml")


def inputs_for(bucket: str, name: str) -> str | None:
    """The gs:// inputs folder if this object is a READY marker under pipeline-inputs/, else None."""
    parts = name.split("/")
    if len(parts) == 3 and parts[0] == "pipeline-inputs" and parts[2] == "READY" and parts[1]:
        return f"gs://{bucket}/pipeline-inputs/{parts[1]}"
    return None


@functions_framework.cloud_event
def on_new_data(event):
    bucket, name = event.data["bucket"], event.data["name"]
    inputs = inputs_for(bucket, name)
    if inputs is None:
        return
    from google.cloud import aiplatform
    run_name = "fixture-auto-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    mount = lambda uri: "/gcs/" + uri.removeprefix("gs://")  # noqa: E731
    job = aiplatform.PipelineJob(
        display_name=run_name, template_path=f"gs://{bucket}/pipeline-templates/latest.json",
        pipeline_root=f"gs://{bucket}/pipeline-root",
        parameter_values={"inputs": mount(inputs), "run_dir": mount(f"gs://{bucket}/pipeline-runs/{run_name}/data"),
                          "harness": HARNESS, "notes": f"automatic run on new data {inputs.rsplit('/', 1)[-1]}"},
        enable_caching=False, project=PROJECT_ID, location=REGION)
    job.submit(service_account=SERVICE_ACCOUNT)
    print(f"submitted {job.resource_name} for {inputs}")
