import importlib
from datetime import timedelta
from modulefinder import Module
from typing import Callable

from django.utils import timezone

from constants.celery_constants import SCRIPTS_QUEUE
from libs.celery_control import safe_apply_async, scripts_celery_app
from libs.sentry import make_error_sentry, SentryTypes


SIX_MINUTELY = "six_minutely"
HOURLY = "hourly"
DAILY = "daily"


class ImportRepeater():
    @classmethod
    def ensure_run(cls, module: Module):
        if hasattr(cls, module.__name__):
            # module was run once
            importlib.reload(module)
        else:
            # this is first run, which means module was just imported (run)
            setattr(cls, module.__name__, True)
        print(f"Ran script '{module.__name__}'")


def queue_script(a_celery_task: Callable, expiry: str):
    """ Forces enqueueing with an expiry. """
    if expiry not in (SIX_MINUTELY, HOURLY, DAILY):
        raise ValueError("Expiry must be one of the constants in this file.")
    
    if expiry == SIX_MINUTELY:
        expiry = (timezone.now() + timedelta(minutes=6)).replace(second=0, microsecond=0)
    if expiry == DAILY:
        expiry = (timezone.now() + timedelta(hours=24)).replace(second=0, microsecond=0)
    if expiry == HOURLY:
        expiry = (timezone.now() + timedelta(hours=1)).replace(second=0, microsecond=0)
    
    print(f"Queueing script '{a_celery_task.__name__}', expires at {expiry}")
    safe_apply_async(
        a_celery_task,
        max_retries=0,
        expires=expiry,
        task_track_started=True,
        task_publish_retry=False,
        retry=False
    )


## ios undecryptable files fix

def create_task_ios_no_decryption_key_task():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("Queueing ios bad decryption keys script.")
        queue_script(celery_process_ios_no_decryption_key, HOURLY)


@scripts_celery_app.task(queue=SCRIPTS_QUEUE)
def celery_process_ios_no_decryption_key():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("running script process_ios_no_decryption_key")
        from scripts import process_ios_no_decryption_key
        ImportRepeater.ensure_run(process_ios_no_decryption_key)


## Log uploads

def create_task_upload_logs():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        queue_script(celery_upload_logs, DAILY)


# run via celery as long as tasks exist
@scripts_celery_app.task(queue=SCRIPTS_QUEUE)
def celery_upload_logs():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("running script upload_logs.")
        from scripts import upload_logs
        ImportRepeater.ensure_run(upload_logs)


## Participant data deletion

def create_task_participant_data_deletion():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("Queueing participant data deletion task.")
        queue_script(celery_participant_data_deletion, HOURLY)


#run via celery as long as tasks exist
@scripts_celery_app.task(queue=SCRIPTS_QUEUE)
def celery_participant_data_deletion():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("running script participant_data_deletion.")
        from scripts import purge_participant_data
        ImportRepeater.ensure_run(purge_participant_data)


# check the forest version in the update_forest_version script
def create_task_update_celery_version():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("Queueing update celery version task.")
        queue_script(celery_update_forest_version, SIX_MINUTELY)


@scripts_celery_app.task(queue=SCRIPTS_QUEUE)
def celery_update_forest_version():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("running script update_forest_version.")
        from scripts import update_forest_version
        ImportRepeater.ensure_run(update_forest_version)


## purge data from invalid timestamps
def create_task_purge_invalid_time_data():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        queue_script(celery_purge_invalid_time_data, DAILY)


# run via celery as long as tasks exist
@scripts_celery_app.task(queue=SCRIPTS_QUEUE)
def celery_purge_invalid_time_data():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("running script upload_logs.")
        from scripts import purge_1970_chunks
        ImportRepeater.ensure_run(purge_1970_chunks)
