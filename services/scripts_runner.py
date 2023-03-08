import importlib
from modulefinder import Module

from constants.celery_constants import SCRIPTS_QUEUE
from libs.celery_control import safe_apply_async, scripts_celery_app
from libs.sentry import make_error_sentry, SentryTypes


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


## ios undecryptable files fix

def create_task_ios_no_decryption_key_task():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("Queueing ios bad decryption keys script.")
        safe_apply_async(celery_process_ios_no_decryption_key)


@scripts_celery_app.task(queue=SCRIPTS_QUEUE)
def celery_process_ios_no_decryption_key():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("running script process_ios_no_decryption_key")
        from scripts import process_ios_no_decryption_key
        ImportRepeater.ensure_run(process_ios_no_decryption_key)


## Log uploads

def create_task_upload_logs():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("Queueing log upload script.")
        safe_apply_async(celery_upload_logs)


#run via celery as long as tasks exist
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
        safe_apply_async(celery_participant_data_deletion)


#run via celery as long as tasks exist
@scripts_celery_app.task(queue=SCRIPTS_QUEUE)
def celery_participant_data_deletion():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("running script participant_data_deletion.")
        from scripts import purge_participant_data
        ImportRepeater.ensure_run(purge_participant_data)