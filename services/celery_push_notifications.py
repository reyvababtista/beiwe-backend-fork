# independent imports
import json
import random
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List

import pytz
# imports that require the path command above be executed
from django.utils import timezone
from django.utils.timezone import make_aware
from firebase_admin.messaging import (AndroidConfig, Message, Notification, QuotaExceededError,
    send as send_notification, ThirdPartyAuthError, UnregisteredError)
from kombu.exceptions import OperationalError

from config.constants import API_TIME_FORMAT, PUSH_NOTIFICATION_SEND_QUEUE, ScheduleTypes
from config.study_constants import OBJECT_ID_ALLOWED_CHARS
from database.schedule_models import ScheduledEvent
from database.user_models import (Participant, ParticipantFCMHistory,
    ParticpantPushNotificationDisabledHistory)
from libs.celery_control import push_send_celery_app
from libs.push_notification_config import (check_firebase_instance, FirebaseMisconfigured,
    set_next_weekly)
from libs.sentry import make_error_sentry


################################################################E###############
############################# PUSH NOTIFICATIONS ###############################
################################################################################

def get_surveys_and_schedules(now):
    """ Mostly this function exists to reduce namespace clutter. """
    # schedule time is in the past, with participants that have fcm tokens.
    # need to filter out unregistered fcms, database schema sucks for that, do it in python. its fine.
    query = ScheduledEvent.objects.filter(
        scheduled_time__lte=now, participant__fcm_tokens__isnull=False, participant__deleted=False,

        # 1) pre-migration, untested
        survey__deleted=False, participant__push_notification_unreachable=False

        # 2) post-migration, untested
        # if the participant has had push notifications disabled this timestamp will be set
        # participant__push_notification_unreachable_timestamp__isnull=False

    ).values_list(
        "survey__object_id",
        "participant__fcm_tokens__token",
        "pk",
        "participant__patient_id",
        "participant__fcm_tokens__unregistered",
    )

    # defaultdicts = clean code, convert to dicts at end.
    # we need a mapping of fcm tokens (a proxy for participants) to surveys and schedule ids (pks)
    surveys = defaultdict(list)
    schedules = defaultdict(list)
    patient_ids = {}
    for survey_obj_id, fcm, schedule_id, patient_id, unregistered in query:
        if unregistered:
            continue
        surveys[fcm].append(survey_obj_id)
        schedules[fcm].append(schedule_id)
        patient_ids[fcm] = patient_id

    return dict(surveys), dict(schedules), patient_ids


def create_push_notification_tasks():
    # we reuse the high level strategy from data processing celery tasks, see that documentation.
    expiry = (datetime.utcnow() + timedelta(minutes=5)).replace(second=30, microsecond=0)
    now = make_aware(datetime.utcnow(), timezone=pytz.utc)
    surveys, schedules, patient_ids = get_surveys_and_schedules(now)
    print(surveys)
    print(schedules)
    print(patient_ids)
    with make_error_sentry('data'):
        if not check_firebase_instance():
            raise FirebaseMisconfigured("Firebase is not configured, cannot queue notifications.")

        # surveys and schedules are guaranteed to have the same keys, assembling the data structures
        # is a pain, so it is factored out. sorry, but not sorry. it was a mess.
        for fcm_token in surveys.keys():
            print(
                f"Queueing up push notification for user {patient_ids[fcm_token]} for {surveys[fcm_token]}")
            safe_queue_push(
                args=[fcm_token, surveys[fcm_token], schedules[fcm_token]],
                max_retries=0,
                expires=expiry,
                task_track_started=True,
                task_publish_retry=False,
                retry=False,
            )


@push_send_celery_app.task(queue=PUSH_NOTIFICATION_SEND_QUEUE)
def celery_send_push_notification(fcm_token: str, survey_obj_ids: List[str], schedule_pks: List[int]):
    ''' Celery task that sends push notifications.   Note that this list of pks may contain duplicates.'''
    patient_id = ParticipantFCMHistory.objects.filter(token=fcm_token) \
        .values_list("participant__patient_id", flat=True).get()

    with make_error_sentry("data"):
        if not check_firebase_instance():
            raise FirebaseMisconfigured(
                "You have not provided credentials for Firebase, notifications cannot be sent."
            )

        # use the earliest timed schedule as our reference for the sent_time parameter.  (why?)
        participant = Participant.objects.get(patient_id=patient_id)
        schedules = ScheduledEvent.objects.filter(pk__in=schedule_pks)
        reference_schedule = schedules.order_by("scheduled_time").first()
        survey_obj_ids = list(set(survey_obj_ids))

        print(f"Sending push notification to {patient_id} for {survey_obj_ids}...")
        try:
            send_push_notification(participant, reference_schedule, survey_obj_ids, fcm_token)
        # error types are documented at firebase.google.com/docs/reference/fcm/rest/v1/ErrorCode
        except UnregisteredError:
            # is an internal 404 http response, it means the token used was wrong.
            # mark the fcm history as out of date.
            failed_send_handler(participant, fcm_token)
            return

        except QuotaExceededError:
            # limits are very high, this is effectively impossible, but it is possible, so we catch it.
            raise

        except ThirdPartyAuthError as e:
            # This means the credentials used were wrong for the target app instance.  This can occur
            # both with bad server credentials, and with bad device credentials.
            # We have only seen this error statement, error name is generic so there may be others.
            if str(e) != "Auth error from APNS or Web Push Service":
                raise
            failed_send_handler(participant, fcm_token)
            return

        success_send_handler(participant, fcm_token, schedules)


def send_push_notification(
        participant: Participant, reference_schedule: ScheduledEvent, survey_obj_ids: List[str],
        fcm_token: str
):
    """ Contains the body of the code to send a notification  """
    # we include a nonce in case of notification deduplication.
    data_kwargs = {
        'nonce': ''.join(random.choice(OBJECT_ID_ALLOWED_CHARS) for _ in range(32)),
        'sent_time': reference_schedule.scheduled_time.strftime(API_TIME_FORMAT),
        'type': 'survey',
        'survey_ids': json.dumps(list(set(survey_obj_ids))),  # Dedupe.
    }

    if participant.os_type == Participant.ANDROID_API:
        message = Message(
            android=AndroidConfig(data=data_kwargs, priority='high'),
            token=fcm_token,
        )
    else:
        display_message = \
            "You have a survey to take." if len(survey_obj_ids) == 1 else "You have surveys to take."
        message = Message(
            data=data_kwargs,
            token=fcm_token,
            notification=Notification( title="Beiwe", body=display_message),
        )
    send_notification(message)


def success_send_handler(participant: Participant, fcm_token: str, schedules: List[ScheduledEvent]):
    # If the query was successful archive the schedules.  Clear the fcm unregistered flag
    # if it was set (this shouldn't happen. ever. but in case we hook in a ui element we need it.)
    print("Push notification send succeeded.")
    fcm_hist = ParticipantFCMHistory.objects.get(token=fcm_token)
    if fcm_hist.unregistered is not None:
        fcm_hist.unregistered = None
        fcm_hist.save()

    create_archives_success(schedules, success=True)
    enqueue_weekly_surveys(participant, schedules)


def failed_send_handler(participant: Participant, fcm_token: str, schedules: List[ScheduledEvent]):
    """ Contains body of code for unregistering a participants push notification behavior.
        Participants get reenabled when they next touch the app checkin endpoint. """

    if participant.push_notification_unreachable_count > 5:
        participant.push_notification_unreachable_count = 0
        participant.save()
        now = timezone.now()
        fcm_hist = ParticipantFCMHistory.objects.get(token=fcm_token)
        fcm_hist.unregistered = now
        ParticpantPushNotificationDisabledHistory(participant=participant, timestamp=now).save()
        print(f"Participant {participant.patient_id} has had push notifications "
              f"disabled after several failed attempts to send.")

    else:
        participant.push_notification_unreachable_count += 1
        participant.save()
        print(f"Participant {participant.patient_id} has had push notifications failures "
              f"incremented to {participant.push_notification_unreachable_count}.")
        return False

    create_archives_success(schedules, success=False)
    enqueue_weekly_surveys(participant, schedules)


def create_archives_success(schedules: List[ScheduledEvent], success: bool):
    """ Populates event history, successes delete source ScheduledEvents. """
    for schedule in schedules:
        schedule.archive(delete=success, success=success)


def enqueue_weekly_surveys(participant: Participant, schedules: List[ScheduledEvent]):
    # set_next_weekly is idempotent until the next weekly event passes.
    for schedule in schedules:
        if schedule.get_schedule_type() == ScheduleTypes.weekly:
            set_next_weekly(participant, schedule.survey)


celery_send_push_notification.max_retries = 0


def safe_queue_push(*args, **kwargs):
    for i in range(10):
        try:
            return celery_send_push_notification.apply_async(*args, **kwargs)
        except OperationalError:
            if i < 3:
                pass
            else:
                raise
