from datetime import datetime, time, timedelta

import pytz
from django.core.validators import MaxValueValidator
from django.db import models
from django.utils.timezone import is_naive, make_aware

from config import constants
from database.common_models import AbstractModel
from database.study_models import SurveyArchive


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
    days_after = models.IntegerField(default=0)
    hour = models.PositiveIntegerField(validators=[MaxValueValidator(23)])
    minute = models.PositiveIntegerField(validators=[MaxValueValidator(59)])

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
        day_of_week is an integer, day 0 is Sunday.

        The timings schema mimics the Java.util.Calendar.DayOfWeek specification: it is zero-indexed
         with day 0 as Sunday."""

    survey = models.ForeignKey('Survey', on_delete=models.PROTECT, related_name='weekly_schedules')
    day_of_week = models.PositiveIntegerField(validators=[MaxValueValidator(6)])
    hour = models.PositiveIntegerField(validators=[MaxValueValidator(23)])
    minute = models.PositiveIntegerField(validators=[MaxValueValidator(59)])

    def get_prior_and_next_event_times(self, now: datetime=None) -> (datetime, datetime):
        """ Identify the start of the week relative to the current time, use that to determine this
        week's (past or present) push notification event time, and the same event for next week.

        If now is passed in it must have a UTC timezone. """

        if now is None:
            # handle case of utc date not matching date of local time.
            today = make_aware(datetime.utcnow(), timezone=pytz.utc).date()
        elif isinstance(now, datetime) and not is_naive(now) and now.tzinfo.zone == "UTC":
            # now must be a datetime with a timezone of UTC
            today = now.date()
        else:
            raise TypeError(f"Datetime must be UTC and timezone aware, received {str(now)}")

        # today.weekday defines Monday=0, in our schema Sunday=0 so we add 1
        start_of_this_week = today - timedelta(days=((today.weekday()+1) % 7))

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
    weekly_schedule = models.ForeignKey('WeeklySchedule', on_delete=models.CASCADE, related_name='scheduled_events', null=True)
    relative_schedule = models.ForeignKey('RelativeSchedule', on_delete=models.CASCADE, related_name='scheduled_events', null=True)
    absolute_schedule = models.ForeignKey('AbsoluteSchedule', on_delete=models.CASCADE, related_name='scheduled_events', null=True)
    scheduled_time = models.DateTimeField()

    class Meta:
        unique_together = ('survey', 'participant', 'scheduled_time',)

    def archive(self, sent_time=None, response_time=None):
        ArchivedEvent.objects.create(
            survey_archive=SurveyArchive.objects.filter(survey=self.survey).order_by('created_on').first(),
            participant=self.participant,
            schedule_type=self.schedule_type,
            scheduled_time=self.scheduled_time,
            sent_time=sent_time,
            response_time=response_time
        ).save()


class ArchivedEvent(AbstractModel):
    survey_archive = models.ForeignKey('SurveyArchive', on_delete=models.PROTECT, related_name='archived_events')
    participant = models.ForeignKey('Participant', on_delete=models.PROTECT, related_name='archived_events')
    schedule_type = models.CharField(max_length=32)
    scheduled_time = models.DateTimeField()
    sent_time = models.DateTimeField(null=True)
    response_time = models.DateTimeField(null=True)
