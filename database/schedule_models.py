from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, tzinfo
from typing import List, Tuple

from django.core.validators import MaxValueValidator
from django.db import models
from django.db.models import Manager
from django.utils import timezone

from constants.common_constants import DEV_TIME_FORMAT
from constants.schedule_constants import ScheduleTypes
from database.common_models import TimestampedModel
from database.survey_models import Survey, SurveyArchive


# this is an import hack to improve IDE assistance
try:
    from database.models import Participant, Study
except ImportError:
    pass


class BadWeeklyCount(Exception): pass


class AbsoluteSchedule(TimestampedModel):
    survey: Survey = models.ForeignKey('Survey', on_delete=models.CASCADE, related_name='absolute_schedules')
    date = models.DateField(null=False, blank=False)
    hour = models.PositiveIntegerField(validators=[MaxValueValidator(23)])
    minute = models.PositiveIntegerField(validators=[MaxValueValidator(59)])
    
    # related field typings (IDE halp)
    scheduled_events: Manager[ScheduledEvent]
    
    @property
    def event_time(self) -> datetime:
        return datetime(
            year=self.date.year,
            month=self.date.month,
            day=self.date.day,
            hour=self.hour,
            minute=self.minute,
            tzinfo=self.survey.study.timezone
        )
    
    @staticmethod
    def create_absolute_schedules(timings: List[List[int]], survey: Survey) -> bool:
        """ Creates new AbsoluteSchedule objects from a frontend-style list of dates and times"""
        survey.absolute_schedules.all().delete()
        
        if survey.deleted or not timings:
            return False
        
        duplicated = False
        for year, month, day, num_seconds in timings:
            _, created = AbsoluteSchedule.objects.get_or_create(
                survey=survey,
                date=date(year=year, month=month, day=day),
                hour=num_seconds // 3600,
                minute=num_seconds % 3600 // 60
            )
            if not created:
                duplicated = True
        
        return duplicated


class RelativeSchedule(TimestampedModel):
    survey: Survey = models.ForeignKey('Survey', on_delete=models.CASCADE, related_name='relative_schedules')
    intervention: Intervention = models.ForeignKey('Intervention', on_delete=models.CASCADE, related_name='relative_schedules', null=True)
    days_after = models.IntegerField(default=0)
    # to be clear: these are absolute times of day, not offsets
    hour = models.PositiveIntegerField(validators=[MaxValueValidator(23)])
    minute = models.PositiveIntegerField(validators=[MaxValueValidator(59)])
    
    # related field typings (IDE halp)
    scheduled_events: Manager[ScheduledEvent]
    
    def scheduled_time(self, intervention_date: date, tz: tzinfo) -> datetime:
        # timezone should be determined externally and passed in
        
        # There is a small difference between applying the timezone via timezone.make_aware and
        # via the tzinfo keyword.  Make_aware seems less weird, so we use that one
        # example order is timezone.make_aware and then tzinfo, input was otherwise identical:
        # datetime.datetime(2020, 12, 5, 14, 30, tzinfo=<DstTzInfo 'America/New_York' EST-1 day, 19:00:00 STD>)
        # datetime.datetime(2020, 12, 5, 14, 30, tzinfo=<DstTzInfo 'America/New_York' LMT-1 day, 19:04:00 STD>)
        
        # the time of day (hour, minute) are not offsets, they are absolute.
        return timezone.make_aware(
            datetime.combine(intervention_date, time(self.hour, self.minute)), tz
        )
    
    @staticmethod
    def create_relative_schedules(timings: List[List[int]], survey: Survey) -> bool:
        """ Creates new RelativeSchedule objects from a frontend-style list of interventions and times
        If you modify this please update create_relative_schedules_by_name in libs.copy_study too. """
        survey.relative_schedules.all().delete()
        if survey.deleted or not timings:
            return False
        
        duplicated = False
        for intervention_id, days_after, num_seconds in timings:
            # using get_or_create to catch duplicate schedules
            _, created = RelativeSchedule.objects.get_or_create(
                survey=survey,
                intervention=Intervention.objects.get(id=intervention_id),
                days_after=days_after,
                hour=num_seconds // 3600,
                minute=num_seconds % 3600 // 60,
            )
            if not created:
                duplicated = True
        
        return duplicated


class WeeklySchedule(TimestampedModel):
    """ Represents an instance of a time of day within a week for the weekly survey schedule.
        day_of_week is an integer, day 0 is Sunday.

        The timings schema mimics the Java.util.Calendar.DayOfWeek specification: it is zero-indexed
         with day 0 as Sunday."""
    
    survey = models.ForeignKey('Survey', on_delete=models.CASCADE, related_name='weekly_schedules')
    day_of_week = models.PositiveIntegerField(validators=[MaxValueValidator(6)])
    hour = models.PositiveIntegerField(validators=[MaxValueValidator(23)])
    minute = models.PositiveIntegerField(validators=[MaxValueValidator(59)])
    
    # related field typings (IDE halp)
    scheduled_events: Manager[ScheduledEvent]
    
    @staticmethod
    def create_weekly_schedules(timings: List[List[int]], survey: Survey) -> bool:
        """ Creates new WeeklySchedule objects from a frontend-style list of seconds into the day. """
        
        if survey.deleted or not timings:
            survey.weekly_schedules.all().delete()
            return False
        
        # asserts are not bypassed in production. Keep.
        if len(timings) != 7:
            raise BadWeeklyCount(
                f"Must have schedule for every day of the week, found {len(timings)} instead."
            )
        survey.weekly_schedules.all().delete()
        
        duplicated = False
        for day in range(7):
            for seconds in timings[day]:
                # should be all ints, use integer division.
                hour = seconds // 3600
                minute = seconds % 3600 // 60
                # using get_or_create to catch duplicate schedules
                _, created = WeeklySchedule.objects.get_or_create(
                    survey=survey, day_of_week=day, hour=hour, minute=minute
                )
                if not created:
                    duplicated = True
        
        return duplicated
    
    @classmethod
    def export_survey_timings(cls, survey: Survey) -> List[List[int]]:
        """Returns a json formatted list of weekly timings for use on the frontend"""
        # this weird sort order results in correctly ordered output.
        fields_ordered = ("hour", "minute", "day_of_week")
        timings = [[], [], [], [], [], [], []]
        schedule_components = WeeklySchedule.objects. \
            filter(survey=survey).order_by(*fields_ordered).values_list(*fields_ordered)
        
        # get, calculate, append, dump.
        for hour, minute, day in schedule_components:
            timings[day].append((hour * 60 * 60) + (minute * 60))
        return timings
    
    def get_prior_and_next_event_times(self, now: datetime) -> Tuple[datetime, datetime]:
        """ Identify the start of the week relative to now, determine this week's push notification
        moment, then add 7 days. tzinfo of input is used to populate tzinfos of return. """
        today = now.date()
        
        # today.weekday defines Monday=0, in our schema Sunday=0 so we add 1
        start_of_this_week = today - timedelta(days=((today.weekday()+1) % 7))
        
        event_this_week = datetime(
            year=start_of_this_week.year,
            month=start_of_this_week.month,
            day=start_of_this_week.day,
            tzinfo=self.survey.study.timezone,
        ) + timedelta(days=self.day_of_week, hours=self.hour, minutes=self.minute)
        event_next_week = event_this_week + timedelta(days=7)
        return event_this_week, event_next_week


class ScheduledEvent(TimestampedModel):
    survey: Survey = models.ForeignKey('Survey', on_delete=models.CASCADE, related_name='scheduled_events')
    participant: Participant = models.ForeignKey('Participant', on_delete=models.PROTECT, related_name='scheduled_events')
    weekly_schedule: WeeklySchedule = models.ForeignKey('WeeklySchedule', on_delete=models.CASCADE, related_name='scheduled_events', null=True, blank=True)
    relative_schedule: RelativeSchedule = models.ForeignKey('RelativeSchedule', on_delete=models.CASCADE, related_name='scheduled_events', null=True, blank=True)
    absolute_schedule: AbsoluteSchedule = models.ForeignKey('AbsoluteSchedule', on_delete=models.CASCADE, related_name='scheduled_events', null=True, blank=True)
    scheduled_time = models.DateTimeField()
    deleted = models.BooleanField(null=False, default=False, db_index=True)
    uuid = models.UUIDField(null=True, blank=True, db_index=True, unique=True)
    checkin_time = models.DateTimeField(null=True, blank=True, db_index=True)
    most_recent_event: ArchivedEvent = models.ForeignKey("ArchivedEvent", on_delete=models.DO_NOTHING, null=True, blank=True)
    
    # due to import complexity (needs those classes) this is the best place to stick the lookup dict.
    SCHEDULE_CLASS_LOOKUP = {
        ScheduleTypes.absolute: AbsoluteSchedule,
        ScheduleTypes.relative: RelativeSchedule,
        ScheduleTypes.weekly: WeeklySchedule,
        AbsoluteSchedule: ScheduleTypes.absolute,
        RelativeSchedule: ScheduleTypes.relative,
        WeeklySchedule: ScheduleTypes.weekly,
    }
    
    @property
    def scheduled_time_in_correct_tz(self) -> datetime:
        # TODO: get participant timezone
        return self.scheduled_time.astimezone(self.survey.study.timezone)
    
    def get_schedule_type(self):
        return self.SCHEDULE_CLASS_LOOKUP[self.get_schedule().__class__]
    
    def get_schedule(self):
        number_schedules = sum((
            self.weekly_schedule is not None,
            self.relative_schedule is not None,
            self.absolute_schedule is not None
        ))
        
        if number_schedules > 1:
            raise Exception(f"ScheduledEvent had {number_schedules} associated schedules.")
        
        if self.weekly_schedule:
            return self.weekly_schedule
        elif self.relative_schedule:
            return self.relative_schedule
        elif self.absolute_schedule:
            return self.absolute_schedule
        else:
            raise Exception("ScheduledEvent had no associated schedule")
    
    def archive(self, self_delete: bool, status: str, created_on: datetime = None):
        """ Create an ArchivedEvent from a ScheduledEvent. """
        # We need to handle the case of no-existing-survey-archive on the referenced survey,  Could
        # be cleaner, but there is an interaction with a migration that will break; not worth it.
        try:
            survey_archive = self.survey.most_recent_archive()
        except SurveyArchive.DoesNotExist:
            self.survey.archive()
            survey_archive = self.survey.most_recent_archive()
        
        # create archive, link archive, conditionally mark self as deleted
        archive = ArchivedEvent(
            survey_archive=survey_archive,
            participant=self.participant,
            schedule_type=self.get_schedule_type(),
            scheduled_time=self.scheduled_time,
            status=status,
            uuid=self.uuid or None,
            **{"created_on": created_on} if created_on else {}  # :D
        )
        archive.save()
        self.update(most_recent_event=archive, deleted=self_delete)


class ArchivedEvent(TimestampedModel):
    # The survey archive cannot point to schedule objects because schedule objects can be deleted
    # (not just marked as deleted)
    survey_archive: SurveyArchive = models.ForeignKey('SurveyArchive', on_delete=models.PROTECT, related_name='archived_events', db_index=True)
    participant: Participant = models.ForeignKey('Participant', on_delete=models.PROTECT, related_name='archived_events', db_index=True)
    schedule_type = models.CharField(null=True, blank=True, max_length=32, db_index=True)
    scheduled_time = models.DateTimeField(null=True, blank=True, db_index=True)
    status = models.TextField(null=False, blank=False, db_index=True)
    uuid = models.UUIDField(null=True, blank=True, db_index=True)
    
    @property
    def survey(self) -> Survey:
        return self.survey_archive.survey


class Intervention(TimestampedModel):
    name = models.TextField()
    study: Study = models.ForeignKey('Study', on_delete=models.PROTECT, related_name='interventions')
    
    # related field typings (IDE halp)
    intervention_dates: Manager[InterventionDate]
    relative_schedules: Manager[RelativeSchedule]


class InterventionDate(TimestampedModel):
    date = models.DateField(null=True, blank=True)
    participant: Participant = models.ForeignKey('Participant', on_delete=models.CASCADE, related_name='intervention_dates')
    intervention: Intervention = models.ForeignKey('Intervention', on_delete=models.CASCADE, related_name='intervention_dates')
    
    class Meta:
        unique_together = ('participant', 'intervention',)


class ParticipantMessageScheduleType:
    absolute = "absolute"
    asap = "asap"
    # relative = "relative"  # Relative to InterventionDate
    
    @classmethod
    def choices(cls):
        return [
            (cls.asap, "as soon as possible"),
            (cls.absolute, "at a specific date/time"),
        ]
    
    @classmethod
    def values(cls):
        return [cls.absolute, cls.asap]  #, cls.relative]


class ParticipantMessageStatus:
    cancelled = "cancelled"
    error = "error"
    scheduled = "scheduled"
    sent = "sent"
    
    @classmethod
    def choices(cls):
        return [(choice, choice.title()) for choice in cls.values()]
    
    @classmethod
    def values(cls):
        return [cls.cancelled, cls.error, cls.scheduled, cls.sent]


class ParticipantMessage(TimestampedModel):
    """
    Model for scheduling messages to be sent to a Participant
    """
    message = models.CharField(max_length=3900)
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name="participant_messages")
    schedule_type = models.TextField(choices=ParticipantMessageScheduleType.choices())
    uuid = models.UUIDField(default=uuid.uuid4)
    
    scheduled_send_datetime = models.DateTimeField(blank=True, null=True)
    # intervention = models.ForeignKey(Intervention, blank=True, null=True, on_delete=models.PROTECT, related_name="participant_messages")
    # timedelta_after_intervention = models.DurationField(blank=True, null=True)
    
    datetime_sent = models.DateTimeField(blank=True, null=True)
    status = models.TextField(choices=ParticipantMessageStatus.choices(), default=ParticipantMessageStatus.scheduled)
    error_message = models.TextField(blank=True, null=True)
    
    @property
    def datetime_sent_display(self):
        return self.datetime_sent.strftime(DEV_TIME_FORMAT)
    
    def message_as_list(self) -> List[str]:
        """
        Returns the message as a list of text where it's split on newline characters. This is to
        help facilitate safe rendering.
        """
        return self.message.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    
    @property
    def scheduled_for(self):
        if self.schedule_type == ParticipantMessageScheduleType.asap:
            return "ASAP"
        else:
            localized_datetime = self.scheduled_send_datetime.astimezone(
                pytz.timezone(self.participant.study.timezone_name)
            )
            return localized_datetime.strftime(DEV_TIME_FORMAT)
    
    def record_successful_send(self):
        self.status = ParticipantMessageStatus.sent
        self.datetime_sent = timezone.now()
        self.save()
    
    def record_error(self, error_msg):
        self.status = ParticipantMessageStatus.error
        self.error_message = error_msg
        self.save()
    
    # def clean(self):
    #     if not self.schedule_type:
    #         pass
    #     elif self.schedule_type == ParticipantMessageScheduleType.relative:
    #         self._validate_fields_as_required(["intervention", "timedelta_after_intervention"])
    #     elif self.schedule_type in [ParticipantMessageScheduleType.absolute, ParticipantMessageScheduleType.asap]:
    #         self._validate_fields_as_required(["scheduled_send_datetime"])
    #     else:
    #         raise NotImplementedError()
    #
    # def _validate_fields_as_required(self, field_names: List[str]):
    #     errors = {}
    #     for field_name in field_names:
    #         if getattr(self, field_name) in EMPTY_VALUES:
    #             errors[field_name] = ValidationError(self._meta.fields[field_name].error_messages["null"], code="null")
    #     if errors:
    #         raise ValidationError(errors)
