import json
from datetime import datetime

from django.db import models
from django.utils import timezone

from config.study_constants import AUDIO_SURVEY_SETTINGS, IMAGE_SURVEY_SETTINGS
from database.common_models import AbstractModel, JSONTextField
from database.validators import LengthValidator


class AbstractSurvey(AbstractModel):
    """ AbstractSurvey contains all fields that we want to have copied into a survey backup whenever
    it is updated. """

    AUDIO_SURVEY = 'audio_survey'
    TRACKING_SURVEY = 'tracking_survey'
    DUMMY_SURVEY = 'dummy'
    IMAGE_SURVEY = 'image_survey'
    SURVEY_TYPE_CHOICES = (
        (AUDIO_SURVEY, AUDIO_SURVEY),
        (TRACKING_SURVEY, TRACKING_SURVEY),
        (DUMMY_SURVEY, DUMMY_SURVEY),
        (IMAGE_SURVEY, IMAGE_SURVEY)
    )

    content = JSONTextField(default='[]', help_text='JSON blob containing information about the survey questions.')
    survey_type = models.CharField(max_length=16, choices=SURVEY_TYPE_CHOICES,
                                   help_text='What type of survey this is.')
    settings = JSONTextField(default='{}', help_text='JSON blob containing settings for the survey.')
    # timings = JSONTextField(default=json.dumps([[], [], [], [], [], [], []]),
    #                         help_text='JSON blob containing the times at which the survey is sent.')

    class Meta:
        abstract = True


class Survey(AbstractSurvey):
    """
    Surveys contain all information the app needs to display the survey correctly to a participant,
    and when it should push the notifications to take the survey.

    Surveys must have a 'survey_type', which is a string declaring the type of survey it
    contains, which the app uses to display the correct interface.

    Surveys contain 'content', which is a JSON blob that is unpacked on the app and displayed
    to the participant in the form indicated by the survey_type.

    Timings schema: a survey must indicate the day of week and time of day on which to trigger;
    by default it contains no values. The timings schema mimics the Java.util.Calendar.DayOfWeek
    specification: it is zero-indexed with day 0 as Sunday. 'timings' is a list of 7 lists, each
    inner list containing any number of times of the day. Times of day are integer values
    indicating the number of seconds past midnight.

    Inherits the following fields from AbstractSurvey
    content
    survey_type
    settings
    timings
    """

    # This is required for file name and path generation
    object_id = models.CharField(max_length=24, unique=True, validators=[LengthValidator(24)])
    # the study field is not inherited because we need to change its related name
    study = models.ForeignKey('Study', on_delete=models.PROTECT, related_name='surveys')
    schedule_type = models.CharField(max_length=32, null=True)

    @classmethod
    def create_with_object_id(cls, **kwargs):
        object_id = cls.generate_objectid_string("object_id")
        survey = cls.objects.create(object_id=object_id, **kwargs)
        return survey

    @classmethod
    def create_with_settings(cls, survey_type, **kwargs):
        """
        Create a new Survey with the provided survey type and attached to the given Study,
        as well as any other given keyword arguments. If the Survey is audio/image and no other
        settings are given, give it the default audio/image survey settings.
        """

        if survey_type == cls.AUDIO_SURVEY and 'settings' not in kwargs:
            kwargs['settings'] = json.dumps(AUDIO_SURVEY_SETTINGS)
        elif survey_type == cls.IMAGE_SURVEY and 'settings' not in kwargs:
            kwargs['settings'] = json.dumps(IMAGE_SURVEY_SETTINGS)

        survey = cls.create_with_object_id(survey_type=survey_type, **kwargs)
        return survey

    def weekly_timings(self):
        """
        Returns a json serializable object that represents the weekly schedules of this survey.
        The return object is a list of 7 lists of ints
        """
        from database.schedule_models import WeeklySchedule
        return WeeklySchedule.export_survey_timings_to_legacy_json(self)

    def relative_timings(self):
        """
        Returns a json serializable object that represents the relative schedules of the survey
        The return object is a list of lists
        """
        schedules = []
        for schedule in self.relative_schedules.all():
            num_seconds = schedule.minute * 60 + schedule.hour * 3600
            schedules.append([schedule.intervention.id, schedule.days_after, num_seconds])
        return schedules

    def absolute_timings(self):
        """
        Returns a json serializable object that represents the absolute schedules of the survey
        The return object is a list of lists
        """
        schedules = []
        for schedule in self.absolute_schedules.all():
            num_seconds = schedule.scheduled_date.minute * 60 + schedule.scheduled_date.hour * 3600
            schedules.append([schedule.scheduled_date.year,
                              schedule.scheduled_date.month,
                              schedule.scheduled_date.day,
                              num_seconds])
        return schedules

    def format_survey_for_study(self):
        survey_dict = self.as_native_python()
        # Make the dict look like the old Mongolia-style dict that the frontend is expecting
        survey_dict.pop('id')
        survey_dict.pop('deleted')
        survey_dict['_id'] = survey_dict.pop('object_id')
        return survey_dict

    def create_absolute_schedules_and_events(self):
        from database.schedule_models import AbsoluteSchedule, ScheduledEvent

        # todo: finish writing, this doesn't work
        for schedule in AbsoluteSchedule.objects.filter(surevy=self).values_list("scheduled_date", flat=True):
            year, month, day, seconds = schedule
            hour = schedule[3] // 3600
            minute = schedule[3] % 3600 // 60
            schedule_date = datetime(schedule[0], schedule[1], schedule[2], hour, minute)

            absolute_schedule = AbsoluteSchedule.objects.create(
                survey=self,
                scheduled_date=schedule_date,
            )
            for participant in self.study.participants.all():
                ScheduledEvent.objects.create(
                    survey=self,
                    participant=participant,
                    weekly_schedule=None,
                    relative_schedule=None,
                    absolute_schedule=absolute_schedule,
                    scheduled_time=schedule_date,
                )


class SurveyArchive(AbstractSurvey):
    """ All fields declared in abstract survey are copied whenever a change is made to a survey """
    archive_start = models.DateTimeField()
    archive_end = models.DateTimeField(default=timezone.now)
    # two new foreign key references
    survey = models.ForeignKey('Survey', on_delete=models.PROTECT, related_name='archives')
    study = models.ForeignKey('Study', on_delete=models.PROTECT, related_name='surveys_archive')
