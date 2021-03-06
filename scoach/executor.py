"""
Provides Executor, a wrapper for a Prefect Flow
"""

import os
import sys
import json
import tempfile
import subprocess
from time import sleep
from typing import Any
from threading import Thread
from functools import partial

import jinja2
import prefect
from prefect import task, Flow
from prefect.engine.state import State
from prefect.executors import DaskExecutor

from scoach.constants import constants
from scoach.logging import logger
from scoach.scheduler import Scheduler
from scoach.utils import (
    get_minio_client,
    load_config_file_to_envs,
    load_env_as_type,
    safe_object_get,
    parse_parameters
)


@task
def setup():
    load_config_file_to_envs()


@task
def update_run_status(run_id: str):
    """
    Task to update the status of a run

    Args:
        - run (Run): the run to update
    """
    from scoach.models import Status, Run
    status = safe_object_get(
        Status, status=constants.RUN_STATUS_RUNNING.value)
    if status is None:
        status = Status(status=constants.RUN_STATUS_RUNNING.value)
        status.save()
    run: Run = safe_object_get(Run, id=run_id)
    run.status = status
    run.save()


@task
def render_template(template_text: str, **kwargs):
    """
    Task to render a jinja2 template

    Args:
        - template_text (str): the text of the template to render
        - **kwargs (dict): the keyword arguments to pass to the template

    Returns:
        - str: the rendered template
    """
    return jinja2.Template(template_text).render(**kwargs)


@task
def execute_template(rendered_template: str, run_id: Any):
    """
    Task to execute a rendered template. Creates a temporary file and
    executes it using the same environment as the current process.

    Args:
        - rendered_template (str): the rendered template to execute
    """
    logger = prefect.context.get("logger")
    logger.info(f"Executing template:\n{rendered_template}")

    # Create a temporary file
    with tempfile.NamedTemporaryFile(mode="w+") as f:
        # Write the template to it
        f.write(rendered_template)
        f.flush()
        os.fsync(f.fileno())

        # Execute the script
        process = subprocess.Popen(
            [sys.executable, f.name],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        # Wait for the process to finish
        while process.poll() is None:
            # Sleep for a while
            logger.debug(f"Run #{run_id} still running")
            sleep(10)

        # Get the output
        stdout, stderr = process.communicate()

        # Log the output
        logger.info(f"stdout:\n{stdout}")
        logger.info(f"stderr:\n{stderr}")


class Executor:  # pylint: disable=too-few-public-methods
    """
    A wrapper for a Prefect Flow
    """

    def __init__(self, scheduler: Scheduler, local: bool = False):
        self._scheduler = scheduler
        self._executor = DaskExecutor(scheduler.address)
        self._local = local

    def _threaded_execution_handler(self, flow: Flow, run_id: str):
        """
        Threaded handler for the flow execution
        """
        from scoach.models import Status, Run
        status = safe_object_get(
            Status, status=constants.RUN_STATUS_QUEUED.value)
        if status is None:
            status = Status(status=constants.RUN_STATUS_QUEUED.value)
            status.save()
        run: Run = safe_object_get(Run, id=run_id)
        run.status = status
        run.save()
        if self._local:
            logger.info("Running locally")
            state: State = flow.run()
        else:
            logger.info("Running on scheduler")
            state: State = flow.run(executor=self._executor)
        while not state.is_finished():
            sleep(0.25)
        if state.is_failed():
            status = safe_object_get(
                Status, status=constants.RUN_STATUS_FAILED.value)
            if status is None:
                status = Status(
                    status=constants.RUN_STATUS_FAILED.value)
                status.save()
            run: Run = safe_object_get(Run, id=run_id)
            run.status = status
            run.save()
            logger.error(
                f"Job {run_id} failed with error: {state.result}")
        elif state.is_successful():
            status = safe_object_get(
                Status, status=constants.RUN_STATUS_COMPLETED.value)
            if status is None:
                status = Status(
                    status=constants.RUN_STATUS_COMPLETED.value)
                status.save()
            run: Run = safe_object_get(Run, id=run_id)
            run.status = status
            run.save()
            logger.info(f"Job {run_id} completed successfully")

    def execute(self, run_id: str):
        """
        Execute the training job
        """
        from scoach.models import Model, Run
        with Flow("Training Flow") as flow:
            setup()
            update_run_status(run_id=run_id)
            minio_client = get_minio_client()
            bucket = load_env_as_type(
                constants.MINIO_BUCKET_ENV.value,
                default=constants.MINIO_BUCKET_ENV_DEFAULT.value,
            )
            run: Run = safe_object_get(Run, id=run_id)
            script_path = run.script.path
            template_text = (
                minio_client.get_object(
                    bucket, script_path).read().decode("utf-8")
            )
            model: Model = run.model
            logger.info(model.config)
            rendered_template = render_template(
                template_text,
                run_id=run_id,
                model_config=f"\"\"\"{model.config}\"\"\"",
                **parse_parameters(json.loads(run.parameters.config)),
            )
            execute_template(rendered_template, run_id)

        thread = Thread(
            target=partial(self._threaded_execution_handler, flow, run_id),
            daemon=True,
        )
        thread.start()
