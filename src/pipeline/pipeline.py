"""The Vertex AI pipeline: rebuild the processed data from a data version, then score the classifier.

  assemble    data/base + data/generated -> data/source     (src/generate)
  ingest      data/source -> data/raw                       (src/ingest)
  preprocess  data/raw -> data/processed                    (src/preprocess)
  evaluate    classify every train message, score, log to W&B (experiments/classifier_tuning)

Every step reads and writes one run folder in the DVC bucket through Vertex AI's
Cloud Storage mount (/gcs/<bucket>/...), using the same code and Data contract
paths as `dvc repro` locally. Images are fixed when the pipeline is compiled
(run_pipeline.sh builds them and passes their tags), so a compiled pipeline
always names the exact code it runs.

Usually run through run_pipeline.sh, which builds the images, uploads the data
version and calls these:
  uv run python pipeline.py compile --data-image ... --tuning-image ... --out pipeline.json
  uv run python pipeline.py submit --template pipeline.json --inputs gs://... --run-name ...
"""

import argparse

from kfp import compiler, dsl

PROJECT_ID = "fixture-ac215-96dhbm"
WANDB_SECRET = f"projects/{PROJECT_ID}/secrets/wandb-api-key/versions/latest"
WANDB_BASE_URL = "https://api.forge.coreweave.com"


def make_pipeline(data_image: str, tuning_image: str):
    """The pipeline function, with both images fixed."""

    def uv_step(directory: str, data_dir: str, extra: str = "") -> dsl.ContainerSpec:
        # DATA_DIR points the service at the run folder, exactly as docker compose does.
        script = f'export DATA_DIR="$0" GIT_COMMIT="$1"; exec uv run --no-sync --directory /app/src/{directory} python main.py {extra}'
        return dsl.ContainerSpec(image=data_image, command=["sh", "-c", script], args=[data_dir, dsl.PIPELINE_JOB_NAME_PLACEHOLDER])

    @dsl.container_component
    def assemble(base: str, generated: str, data_dir: str):
        return dsl.ContainerSpec(
            image=data_image,
            command=["uv", "run", "--no-sync", "--directory", "/app/src/generate", "python", "main.py", "assemble"],
            args=["--base", base, "--generated", generated, "--out", dsl.ConcatPlaceholder([data_dir, "/source"])])

    @dsl.container_component
    def ingest(data_dir: str):
        return uv_step("ingest", data_dir)

    @dsl.container_component
    def preprocess(data_dir: str):
        return uv_step("preprocess", data_dir)

    @dsl.container_component
    def evaluate(data_dir: str, harness: str, notes: str):
        return dsl.ContainerSpec(image=tuning_image, command=["python", "main.py"],
                                 args=["--data-root", data_dir, "--harness", harness, "--notes", notes])

    @dsl.pipeline(name="fixture-data-and-eval",
                  description="Rebuild processed data from a data version, then score the classifier in W&B")
    def fixture_pipeline(inputs: str, run_dir: str, harness: str = "harnesses/prod_v1.yaml",
                         notes: str = "pipeline run"):
        # inputs and run_dir are /gcs/<bucket>/... paths (Vertex AI mounts Cloud Storage there).
        a = assemble(base=f"{inputs}/base", generated=f"{inputs}/generated", data_dir=run_dir)
        i = ingest(data_dir=run_dir).after(a)
        p = preprocess(data_dir=run_dir).after(i)
        e = evaluate(data_dir=run_dir, harness=harness, notes=notes).after(p)
        e.set_env_variable("WANDB_API_KEY_SECRET", WANDB_SECRET)
        e.set_env_variable("WANDB_BASE_URL", WANDB_BASE_URL)
        e.set_env_variable("GOOGLE_CLOUD_PROJECT", PROJECT_ID)
        for task in (a, i, p, e):
            task.set_caching_options(False)  # every run must really rebuild and rescore

    return fixture_pipeline


def submit(template: str, inputs: str, run_name: str, harness: str, notes: str, bucket: str,
           service_account: str, region: str, wait: bool) -> str:
    """Start one pipeline run on Vertex AI. inputs is a gs:// folder holding base/ and generated/."""
    from google.cloud import aiplatform
    to_mount = lambda uri: "/gcs/" + uri.removeprefix("gs://")  # noqa: E731  (Vertex mounts buckets at /gcs)
    job = aiplatform.PipelineJob(
        display_name=run_name, template_path=template, pipeline_root=f"{bucket}/pipeline-root",
        parameter_values={"inputs": to_mount(inputs), "run_dir": to_mount(f"{bucket}/pipeline-runs/{run_name}/data"),
                          "harness": harness, "notes": notes},
        enable_caching=False, project=PROJECT_ID, location=region)
    job.submit(service_account=service_account)
    print(f"submitted {job.resource_name}\n{job._dashboard_uri()}")
    if wait:
        job.wait()
    return job.resource_name


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    c = sub.add_parser("compile")
    c.add_argument("--data-image", required=True)
    c.add_argument("--tuning-image", required=True)
    c.add_argument("--out", default="pipeline.json")
    s = sub.add_parser("submit")
    s.add_argument("--template", required=True, help="compiled pipeline.json (local or gs://)")
    s.add_argument("--inputs", required=True, help="gs:// folder with base/ and generated/")
    s.add_argument("--run-name", required=True)
    s.add_argument("--harness", default="harnesses/prod_v1.yaml")
    s.add_argument("--notes", default="pipeline run")
    s.add_argument("--bucket", default="gs://fixture-ac215-96dhbm-dvc")
    s.add_argument("--service-account", default=f"fixture-tuning@{PROJECT_ID}.iam.gserviceaccount.com")
    s.add_argument("--region", default="us-east1")
    s.add_argument("--wait", action="store_true")
    args = p.parse_args(argv)
    if args.command == "compile":
        compiler.Compiler().compile(make_pipeline(args.data_image, args.tuning_image), args.out)
        print(f"compiled {args.out}")
    else:
        submit(args.template, args.inputs, args.run_name, args.harness, args.notes, args.bucket,
               args.service_account, args.region, args.wait)


if __name__ == "__main__":
    main()
