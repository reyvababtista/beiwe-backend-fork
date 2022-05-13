from constants.celery_constants import FOREST_QUEUE
from libs.celery_control import forest_celery_app, safe_apply_async
from libs.sentry import make_error_sentry, SentryTypes


def create_process_ios_no_decryption_key_task():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("Queueing ios bad decryption keys script.")
        safe_apply_async(celery_process_ios_no_decryption_key)


#run via celery as long as tasks exist
@forest_celery_app.task(queue=FOREST_QUEUE)
def celery_process_ios_no_decryption_key():
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        print("running ios bad decryption keys script.")
        from scripts import process_ios_no_decryption_key  # noqa
