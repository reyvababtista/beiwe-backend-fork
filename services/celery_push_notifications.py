from datetime import datetime, timedelta
from os.path import abspath
from sys import path

path.insert(0, abspath(__file__).rsplit('/', 2)[0])

import pytz

from django.utils.timezone import make_aware
from firebase_admin.messaging import Message, send
from kombu.exceptions import OperationalError

from config.constants import API_TIME_FORMAT, ScheduleTypes
from database.schedule_models import ScheduledEvent
from database.survey_models import Survey
from database.user_models import Participant
from libs.celery_control import push_send_celery_app
from libs.push_notifications import firebase_app, FirebaseNotCredentialed, set_next_weekly
from libs.sentry import make_error_sentry


################################################################################
############################## Task Endpoints ##################################
################################################################################

@push_send_celery_app.task
def queue_push_notification(participant):
    return celery_send_push_notification(participant)
queue_push_notification.max_retries = 0  # may not be necessary

################################################################################
############################# Data Processing ##################################
################################################################################


def create_push_notification_tasks():
    expiry = (datetime.now() + timedelta(minutes=5)).replace(second=30, microsecond=0)
    now = make_aware(datetime.utcnow(), timezone=pytz.utc)
    event_query = ScheduledEvent.objects.filter(scheduled_time__lte=now).values_list(
        "survey__object_id", "participant__fcm_instance_id", "pk"
    )

    with make_error_sentry('data'):
        if not firebase_app:
            raise FirebaseNotCredentialed("Firebase is not configured, cannot queue notifications.")

        for survey_obj_id, fcm_token, sched_pk in event_query:
            safe_queue_push(
                args=[survey_obj_id, fcm_token, sched_pk],
                max_retries=0,
                expires=expiry,
                task_track_started=True,
                task_publish_retry=False,
                retry=False,
            )


def celery_send_push_notification(survey_obj_id: str, fcm_token: str, sched_pk: int):
    ''' Celery task that sends push notifications. '''
    with make_error_sentry("data"):

        if not firebase_app:
            raise FirebaseNotCredentialed(
                "You have not provided credentials for Firebase, notifications cannot be sent"
            )

        # This if the schedule object doesn't exist, error.  This indicates a broken
        schedule = ScheduledEvent.objects.get(pk=sched_pk)
        is_weekly = schedule.get_schedule_type() == ScheduleTypes.weekly

        # do not remove this assignment (yet), its presence in the namespace may have meaning.
        response = send(Message(
            data={
                'type': 'survey',
                'survey_id': survey_obj_id,
                'sent_time': schedule.schedule_time.strptime(API_TIME_FORMAT),
            },
            token=fcm_token,
        ))

        # if err_sentry.errors:
        #     err_sentry.raise_errors()
        #
        # if "response" in vars():
        #     print(response)
        #     from pprint import pprint
        #     pprint(vars(response))

        schedule.archive()

        if is_weekly:
            set_next_weekly(
                Participant.objects.get(fcm_instance_id=fcm_token),
                Survey.objects.get(object_id=survey_obj_id),
            )


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
