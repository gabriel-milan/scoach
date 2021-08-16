import yaml
from pathlib import Path

import typer

from coach.constants import constants

app = typer.Typer()


def check_config():
    """
    Check if the config file exists.
    """
    if not constants.COACH_DEFAULT_CONFIG_PATH.value.exists():
        print("No config file found. Please run `coach init` to create one.")
        return False
    from coach.utils import load_config_file_to_envs
    load_config_file_to_envs()
    return True


@app.command()
def init():
    """
    Initialize (or override) configuration file.
    """
    # REDIS_HOST: localhost
    # REDIS_PORT: 6379
    # REDIS_DB: 0
    # REDIS_PASSWORD: ""
    # REDIS_QUEUE_NAME: "queue_name"
    # DB_CONNECTION_STRING: "sqlite:///:memory:"
    # SLURM_PARTITION: "debug"
    # SLURM_CORES_PER_JOB: 1
    # SLURM_MEMORY_PER_JOB: "1G"
    # SLURM_WORKER_NAME: "worker_name"
    # SLURM_JOB_EXCLUSIVE: false
    # SLURM_MAX_WORKERS: 1
    # MINIO_ENDPOINT: "minio.example.com"
    # MINIO_ACCESS_KEY: "minio_access_key"
    # MINIO_SECRET_KEY: "minio_secret_key"
    # MINIO_BUCKET: "minio_bucket_name"
    redis_host = typer.prompt("Redis Host")
    redis_port = typer.prompt("Redis Port", default=6379)
    redis_db = typer.prompt("Redis DB", default=0)
    redis_password = typer.prompt("Redis Password", default="")
    redis_queue_name = typer.prompt("Redis Queue Name")
    db_connection_string = typer.prompt("DB Connection String")
    slurm_partition = typer.prompt("SLURM Partition")
    slurm_cores_per_job = typer.prompt("SLURM Cores Per Job", default=1)
    slurm_memory_per_job = typer.prompt("SLURM Memory Per Job", default="1G")
    slurm_worker_name = typer.prompt(
        "SLURM Worker Name", default="worker_name")
    slurm_job_exclusive = typer.prompt(
        "SLURM Job Exclusive", default=False, show_choices=True, type=bool
    )
    slurm_max_workers = typer.prompt("SLURM Max Workers", default=1)
    minio_endpoint = typer.prompt("Minio Endpoint")
    minio_access_key = typer.prompt("Minio Access Key")
    minio_secret_key = typer.prompt("Minio Secret Key")
    minio_bucket = typer.prompt("Minio Bucket")

    # Save configs to YAML file
    config_path = Path(constants.COACH_DEFAULT_CONFIG_PATH.value)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        yaml.dump(
            {
                "REDIS_HOST": redis_host,
                "REDIS_PORT": redis_port,
                "REDIS_DB": redis_db,
                "REDIS_PASSWORD": redis_password,
                "REDIS_QUEUE_NAME": redis_queue_name,
                "DB_CONNECTION_STRING": db_connection_string,
                "SLURM_PARTITION": slurm_partition,
                "SLURM_CORES_PER_JOB": slurm_cores_per_job,
                "SLURM_MEMORY_PER_JOB": slurm_memory_per_job,
                "SLURM_WORKER_NAME": slurm_worker_name,
                "SLURM_JOB_EXCLUSIVE": slurm_job_exclusive,
                "SLURM_MAX_WORKERS": slurm_max_workers,
                "MINIO_ENDPOINT": minio_endpoint,
                "MINIO_ACCESS_KEY": minio_access_key,
                "MINIO_SECRET_KEY": minio_secret_key,
                "MINIO_BUCKET": minio_bucket,
            }
        )
    )
    typer.echo(
        f"Config file created at {constants.COACH_DEFAULT_CONFIG_PATH.value}.")


@ app.command()
def daemon():
    """
    Run daemon process for SLURM login machine.
    """
    if not check_config():
        return
    from coach.coach import Coach
    c = Coach()
    c.start_scheduler()


@ app.command()
def submit(python_script: Path, job_config: Path, model_config: Path):
    """
    Submits a job to the queue.
    """
    if not check_config():
        return
    # Check if all paths exists
    if not python_script.exists():
        typer.echo("Python script does not exist.")
        return
    if not job_config.exists():
        typer.echo("Job config does not exist.")
        return
    if not model_config.exists():
        typer.echo("Model config does not exist.")
        return
    # Load job_config json
    with job_config.open() as f:
        job_config = json.load(f)
    # Load model_config json
    with model_config.open() as f:
        model_config = json.load(f)
    # Submit job
    from coach.coach import Coach
    c = Coach()
    run_id = c.submit_job(str(python_script), job_config, model_config)
    typer.echo(f"Submitted job with run id {run_id}")


@ app.command()
def list():
    """
    List all jobs.
    """
    if not check_config():
        return
    from coach.db import list_all_runs
    runs = list_all_runs()
    typer.echo(f"Found {len(runs)} runs.")
    for i, run in enumerate(runs):
        typer.echo(f"{i + 1}. {run}")


@ app.command()
def show(run_id: str):
    """
    Shows a single run from the database.
    """
    if not check_config():
        return
    from coach.db import get_run
    run = get_run(run_id)
    if run is None:
        typer.echo(f"Run {run_id} not found.")
        typer.echo("It may be still on training though, please wait a while")
        return
    typer.echo(f"Run {run_id} is available!")
    typer.echo(f"Information: {run}")
    typer.echo(
        "If you desire to load this model, open a Python shell and do the following:")
    typer.echo(">>> from coach.utils import load_config_file_to_envs")
    typer.echo(">>> from coach.db import load_run")
    typer.echo(">>> load_config_file_to_envs()")
    typer.echo(">>> model = load_run(run_id)")