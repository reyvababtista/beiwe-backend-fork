from datetime import datetime
from os.path import exists

import pytz
from django.utils.timezone import make_aware
from firebase_admin import credentials, initialize_app as initialize_firebase_app

from config.constants import FIREBASE_CREDENTIAL_LOCATION
from database.schedule_models import AbsoluteSchedule, ScheduledEvent, WeeklySchedule
from database.survey_models import Survey
from database.user_models import Participant

# setup firebase
if exists(FIREBASE_CREDENTIAL_LOCATION):
    firebase_app = initialize_firebase_app(credentials.Certificate(FIREBASE_CREDENTIAL_LOCATION))
else:
    firebase_app = None


class FirebaseNotCredentialed(Exception): pass


def set_next_weekly(participant: Participant, survey: Survey):
    ''' Create a next ScheduledEvent for a survey for a particular participant. '''
    schedule_date, schedule = get_next_weekly_event(survey)

    # this handles the case where the schedule was deleted. This is a corner case that shouldn't happen
    if schedule_date is not None and schedule is not None:
        ScheduledEvent.objects.create(
            survey=survey,
            participant=participant,
            weekly_schedule=schedule,
            relative_schedule=None,
            absolute_schedule=None,
            scheduled_time=schedule_date,
        )


def get_next_weekly_event(survey) -> ((datetime, None), (WeeklySchedule, None)):
    """ Determines the next time for a particular survey, provides the relevant weekly schedule. """
    now = make_aware(datetime.utcnow(), timezone=pytz.utc)
    timing_list = []
    for weekly_schedule in survey.weekly_schedules.all():
        this_week, next_week = weekly_schedule.get_prior_and_next_event_times(now)
        if now < this_week:
            relevant_date = this_week
        else:
            relevant_date = next_week
        timing_list.append((relevant_date, weekly_schedule))

    # handle case where there are no scheduled events
    if not timing_list:
        return None, None

    timing_list.sort(key=lambda date_and_schedule: date_and_schedule[0])
    schedule_date, schedule = timing_list[0]
    return schedule_date, schedule


def repopulate_weekly_survey_schedule_events(survey: Survey):
    """ Clear existing schedules, get participants, bulk create schedules """
    print(survey.scheduled_events.all())
    print(survey.scheduled_events.filter(relative_schedule=None, absolute_schedule=None))
    survey.scheduled_events.filter(relative_schedule=None, absolute_schedule=None).delete()
    schedule_date, schedule = get_next_weekly_event(survey)
    participants = survey.study.participants.all()
    new_events = []
    for participant in participants:
        new_events.append(ScheduledEvent(
            survey=survey,
            participant=participant,
            weekly_schedule=schedule,
            relative_schedule=None,
            absolute_schedule=None,
            scheduled_time=schedule_date,
        ))

    ScheduledEvent.objects.bulk_create(new_events)


def repopulate_absolute_survey_schedule_events(survey: Survey):
    survey.scheduled_events.filter(relative_schedule=None, weekly_schedule=None).delete()
    new_events = []
    for schedule in survey.absolute_schedules.all():
        for participant in survey.study.participants.all():
            new_events.append(ScheduledEvent(
                survey=survey,
                participant=participant,
                weekly_schedule=None,
                relative_schedule=None,
                absolute_schedule=schedule,
                scheduled_time=schedule.scheduled_date,
            ))

    ScheduledEvent.objects.bulk_create(new_events)


