from datetime import datetime, time, timedelta

import pytz
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils.timezone import is_naive, make_aware

from config import constants
from database.common_models import AbstractModel


class AbsoluteSchedule(AbstractModel):
    survey = models.ForeignKey('Survey', on_delete=models.PROTECT, related_name='absolute_schedules')
    scheduled_date = models.DateTimeField()

    def create_events(self):
        for participant in self.survey.study.participants.all():
            ScheduledEvent.objects.create(
                survey=self.survey,
                participant=participant,
                schedule_type=constants.ScheduleTypes.absolute,
                scheduled_time=self.scheduled_date,
            ).save()


class RelativeSchedule(AbstractModel):
    survey = models.ForeignKey('Survey', on_delete=models.PROTECT, related_name='relative_schedules')
    participant = models.ForeignKey('Participant', on_delete=models.PROTECT, related_name='relative_schedules')
    days_after = models.PositiveIntegerField(default=0)
    hour = models.PositiveIntegerField(validators=MaxValueValidator(23))
    minute = models.PositiveIntegerField(validators=MaxValueValidator(59))

    def create_event(self):
        scheduled_time = datetime.combine(
            self.participant.intervention_date, time(self.hour, self.minute)
        )
        ScheduledEvent.objects.create(
            survey=self.survey,
            participant=self.participant,
            schedule_type=constants.ScheduleTypes.relative,
            scheduled_time=scheduled_time,
        ).save()


class WeeklySchedule(AbstractModel):
    """ Represents an instance of a time of day within a week for the weekly survey schedule.
        day_of_week is an integer, day 0 is Sunday. """

    survey = models.ForeignKey('Survey', on_delete=models.PROTECT, related_name='weekly_schedules')
    day_of_week = models.PositiveIntegerField(validators=MaxValueValidator(6))
    hour = models.PositiveIntegerField(validators=MaxValueValidator(23))
    minute = models.PositiveIntegerField(validators=MaxValueValidator(59))

    def get_prior_and_next_event_times(self, now:datetime=None) -> (datetime, datetime):
        """ Identify the start of the week relative to the current time, use that to determine this
        week's (past or present) push notification event time, and the same event for next week.

        If now is passed in it must have a UTC timezone. """

        if now is None:
            # handle case of utc date not matching date of local time.
            today = make_aware(datetime.utcnow(), timezone=pytz.utc).date
        elif not isinstance(now, datetime) or is_naive(now) or now.tzinfo.zone != "UTC":
            raise TypeError(f"(1) Datetime must be UTC and timezone aware, received {str(now)}")
        else:
            # shouldn't be reachable, fixes IDE complaints.
            raise TypeError(f"(2) Datetime must be UTC and timezone aware, received {str(now)}")

        start_of_this_week = today - timedelta(days=today.weekday())

        event_this_week = make_aware(
                datetime(
                    year=start_of_this_week.year,
                    month=start_of_this_week.month,
                    day=start_of_this_week.day,
                ) +
                timedelta(
                    days=self.day_of_week,
                    hours=self.hour,
                    minutes=self.minute,
                ),
                timezone=pytz.utc,
        )
        event_next_week = event_this_week + timedelta(days=7)
        return event_this_week, event_next_week


class ScheduledEvent(AbstractModel):
    survey = models.ForeignKey('Survey', on_delete=models.PROTECT, related_name='scheduled_events')
    participant = models.ForeignKey('Participant', on_delete=models.PROTECT, related_name='scheduled_events')
    schedule_type = models.CharField(choice=constants.ScheduleTypes.choices())
    scheduled_time = models.DateTimeField()
    is_active = models.BooleanField(default=True)


class ArchivedEvent(AbstractModel):
    survey = models.ForeignKey('Survey', on_delete=models.PROTECT, related_name='archived_events')
    participant = models.ForeignKey('Participant', on_delete=models.PROTECT, related_name='archived_events')
    schedule_type = models.CharField(choice=constants.ScheduleTypes.choices())
    scheduled_time = models.DateTimeField()
    sent_time = models.DateTimeField(null=True)
    response_time = models.DateTimeField(null=True)
