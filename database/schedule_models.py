import datetime

from django.core.validators import MaxValueValidator
from django.db import models

from config import constants
from database.common_models import AbstractModel


class AbsoluteSchedule(AbstractModel):
    survey = models.ForeignKey('Survey', on_delete=models.PROTECT,
                               related_name='absolute_schedules')
    scheduled_date = models.DateTimeField()

    def create_events(self):
        for participant in self.survey.study.participants.all():
            ScheduledEvent.objects.create(survey=self.survey,
                                          participant=participant,
                                          schedule_type=constants.ScheduleTypes.absolute,
                                          scheduled_time=self.scheduled_date).save()


class RelativeSchedule(AbstractModel):
    survey = models.ForeignKey('Survey', on_delete=models.PROTECT,
                               related_name='relative_schedules')
    participant = models.ForeignKey('Participant', on_delete=models.PROTECT,
                                    related_name='relative_schedules')
    days_after = models.IntegerField(default=0)
    hour = models.PositiveIntegerField(validators=MaxValueValidator(23))
    minute = models.PositiveIntegerField(validators=MaxValueValidator(59))

    def create_event(self):
        scheduled_time = datetime.datetime.combine(self.participant.intervention_date,
                                                   datetime.time(self.hour, self.minute))
        ScheduledEvent.objects.create(survey=self.survey,
                                      participant=self.participant,
                                      schedule_type=constants.ScheduleTypes.relative,
                                      scheduled_time=scheduled_time).save()


class WeeklySchedule(AbstractModel):
    survey = models.ForeignKey('Survey', on_delete=models.PROTECT,
                               related_name='weekly_schedules')
    day_of_week = models.CharField(choices=constants.WEEKDAY_CHOICES)
    hour = models.PositiveIntegerField(validators=MaxValueValidator(23))
    minute = models.PositiveIntegerField(validators=MaxValueValidator(59))


class ScheduledEvent(AbstractModel):
    survey = models.ForeignKey('Survey', on_delete=models.PROTECT,
                               related_name='scheduled_events')
    participant = models.ForeignKey('Participant', on_delete=models.PROTECT,
                                    related_name='scheduled_events')
    schedule_type = models.CharField(choice=constants.ScheduleTypes.choices())
    scheduled_time = models.DateTimeField()
    is_active = models.BooleanField(default=True)


class ArchivedEvent(AbstractModel):
    survey = models.ForeignKey('Survey', on_delete=models.PROTECT,
                               related_name='archived_events')
    participant = models.ForeignKey('Participant', on_delete=models.PROTECT,
                                    related_name='archived_events')
    schedule_type = models.CharField(choice=constants.ScheduleTypes.choices())
    scheduled_time = models.DateTimeField()
    sent_time = models.DateTimeField(null=True)
    response_time = models.DateTimeField(null=True)
