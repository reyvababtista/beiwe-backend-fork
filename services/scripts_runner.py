from constants.celery_constants import SCRIPTS_QUEUE
from libs.celery_control import safe_apply_async, scripts_celery_app
from libs.sentry import make_error_sentry, SentryTypes


## ios undecryptable files fix

def create_task_ios_no_decryption_key_task():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("Queueing ios bad decryption keys script.")
        safe_apply_async(celery_process_ios_no_decryption_key)


@scripts_celery_app.task(queue=SCRIPTS_QUEUE)
def celery_process_ios_no_decryption_key():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("running ios bad decryption keys script.")
        from scripts import process_ios_no_decryption_key  # noqa
    exit(0)  # this is the easiest way to fix the need to reload the import.


## Log uploads

def create_task_upload_logs():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("Queueing log upload script.")
        safe_apply_async(celery_process_ios_no_decryption_key)


#run via celery as long as tasks exist
@scripts_celery_app.task(queue=SCRIPTS_QUEUE)
def celery_upload_logs():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("running log upload script.")
        from scripts import upload_logs  # noqa
    exit(0)
