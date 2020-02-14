from os.path import abspath
from sys import path

# add the root of the project into the path to allow cd-ing into this folder and running the script.
path.insert(0, abspath(__file__).rsplit('/', 2)[0])

from config.load_django import django_loaded; assert django_loaded

from datetime import datetime, timedelta
from libs.sentry import make_error_sentry

from kombu.exceptions import OperationalError
from libs.celery import celery_app


################################################################################
############################## Task Endpoints ##################################
################################################################################

@celery_app.task
def queue_push_notification(participant):
    return celery_send_push_notification(participant)
queue_push_notification.max_retries = 0  # may not be necessary

################################################################################
############################# Data Processing ##################################
################################################################################


def create_push_notification_tasks():
    # set the tasks to expire at the 5 minutes and thirty seconds mark after the most recent
    # 5 minutely cron task. This way all tasks will be revoked at the same, and well-known, instant.
    # 30 seconds grace period is 30 seconds out of
    expiry = (datetime.now() + timedelta(minutes=4)).replace(second=30, microsecond=0)

    with make_error_sentry('data'):
        pass



def celery_send_push_notification(participant_id):
    pass

def safe_queue_push(*args, **kwargs):
    for i in range(10):
        try:
            return queue_push_notification.apply_async(*args, **kwargs)
        except OperationalError:
            if i < 3:
                pass
            else:
                raise


# Running this file will enqueue users
if __name__ == "__main__":
    create_push_notification_tasks()
