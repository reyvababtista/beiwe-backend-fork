from datetime import datetime
from os.path import exists

import pytz

from config.load_django import django_loaded; assert django_loaded

from database.schedule_models import ScheduledEvent, AbsoluteSchedule
from django.utils.timezone import make_aware
from firebase_admin import credentials, initialize_app as initialize_firebase_app


# setup firebase
if exists("private/serviceAccountKey.json"):
    firebase_app = initialize_firebase_app(credentials.Certificate("private/serviceAccountKey.json"))
else:
    firebase_app = None


class FirebaseNotCredentialed(Exception): pass


# fixme: this creates events for all users, it needs to create events for a specific user
def create_next_weekly_event(survey):
    now = make_aware(datetime.utcnow(), timezone=pytz.utc)
    timing_list =[]
    for schedule in survey.weekly_schedules.all():
        this_week, next_week = schedule.get_prior_and_next_event_times(now)
        if now < this_week:
            relevant_date = this_week
        else:
            relevant_date = next_week
        timing_list.append((relevant_date, schedule))

    # handle case where there are no scheduled events
    if not timing_list:
        return

    timing_list.sort(key=lambda date_and_schedule: date_and_schedule[0])
    schedule_date, schedule = timing_list[0]
    for participant in survey.study.participants.all():
        ScheduledEvent.objects.create(
            survey=survey,
            participant=participant,
            weekly_schedule=schedule,
            relative_schedule=None,
            absolute_schedule=None,
            scheduled_time=schedule_date,
        )


def create_absolute_schedules_and_events(survey):
    # TODO rename schedules variable
    schedules = survey.timings["schedule"]
    for schedule in schedules:
        hour = schedule[3] // 3600
        minute = schedule[3] % 3600 // 60
        schedule_date = datetime(schedule[0], schedule[1], schedule[2], hour, minute)
        absolute_schedule = AbsoluteSchedule.objects.create(
            survey=survey,
            scheduled_date=schedule_date,
        )
        for participant in survey.study.participants.all():
            ScheduledEvent.objects.create(
                survey=survey,
                participant=participant,
                weekly_schedule=None,
                relative_schedule=None,
                absolute_schedule=absolute_schedule,
                scheduled_time=schedule_date,
            )
