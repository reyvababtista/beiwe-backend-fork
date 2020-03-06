import json
from os import path
from plistlib import Dict
from typing import List

from flask import flash, request

from database.schedule_models import AbsoluteSchedule, RelativeSchedule, WeeklySchedule
from database.study_models import Study
from database.survey_models import Survey

NoneType = type(None)

WEEKLY_SCHEDULE_KEY = "timings"  # predates the other schedules
ABSOLUTE_SCHEDULE_KEY = "absolute_timings"
RELATIVE_SCHEDULE_KEY = "relative_timings"

# keys used if various places, pulled out into constants for consistency.
CREATED_ON_KEY = 'created_on'
DEVICE_SETTINGS_KEY = 'device_settings'
STUDY_KEY = 'study'
SURVEY_CONTENT_KEY = 'content'
SURVEY_SETTINGS_KEY = 'settings'
SURVEYS_KEY = 'surveys'

# "_id" is legacy, pk shouldn't occur
FIELDS_TO_PURGE = ('_id', 'id', 'pk',  'created_on', 'last_updated', 'object_id')

# ID_FIELDS = ("id", "_id")


def purge_unnecessary_fields(d: dict):
    """ removes fields that we don't want re-imported, does so silently. """
    for field in FIELDS_TO_PURGE:
        d.pop(field, None)


def allowed_file_extension(filename: str):
    """ Does filename end with ".json" (case-insensitive) """
    assert isinstance(filename, str)  # python3, could be a bytes, the line below would always fail.
    return path.splitext(filename)[1].lower() == '.json'


def copy_existing_study(new_study: Study, old_study: Study):
    """ copy logic for an existing study """
    old_device_settings = old_study.device_settings.as_dict()
    old_device_settings.pop(STUDY_KEY)
    msg = update_device_settings(old_device_settings, new_study, old_study.name)

    surveys_to_copy = []
    for survey in old_study.surveys.all():
        survey_as_dict = survey.as_dict()
        survey_as_dict.pop(STUDY_KEY, None)
        survey_as_dict.pop(CREATED_ON_KEY, None)
        surveys_to_copy.append(survey_as_dict)
    msg += " \n" + add_new_surveys(surveys_to_copy, new_study, old_study.name)
    flash(msg, 'success')


def update_device_settings(new_device_settings, study, filename):
    """ Takes the provided loaded json serialization of a study's device settings and
    updates the provided study's device settings.  Handles the cases of different legacy
    serialization of the consent_sections parameter. """

    if request.form.get('device_settings', None) == 'true':
        # Don't copy the PK to the device settings to be updated
        purge_unnecessary_fields(new_device_settings)
        
        # ah, it looks like the bug we had was that you can just send dictionary directly
        # into a textfield and it uses the __repr__ or __str__ or __unicode__ function, causing
        # weirdnesses if as_native_python is called because json does not want to use double quotes.
        if isinstance(new_device_settings['consent_sections'], dict):
            new_device_settings['consent_sections'] = json.dumps(new_device_settings['consent_sections'])
        
        study.device_settings.update(**new_device_settings)
        return f"Overwrote {study.name}'s App Settings with the values from {filename}."
    else:
        return f"Did not alter {study.name}'s App Settings."


def add_new_surveys(new_survey_settings: List[Dict], study: Study, filename: str):
    # surveys are always provided, there is a checkbox about whether to import them
    if request.form.get('surveys', None) != 'true':
        return "Copied 0 Surveys and 0 Audio Surveys from %s to %s." % (filename, study.name)

    surveys_added, audio_surveys_added, image_surveys_added = 0, 0, 0
    for survey_settings in new_survey_settings:
        # clean out the keys we don't want/need and pop the schedules.
        purge_unnecessary_fields(survey_settings)
        weekly_schedules = survey_settings.pop(WEEKLY_SCHEDULE_KEY, None)
        absolute_schedules = survey_settings.pop(ABSOLUTE_SCHEDULE_KEY, None)
        relative_schedules = survey_settings.pop(RELATIVE_SCHEDULE_KEY, None)

        # some sanity typechecking here
        assert isinstance(weekly_schedules, (list, NoneType)), f"weekly_schedule was a {type(weekly_schedules)}."
        assert isinstance(absolute_schedules, (list, NoneType)), f"absolute_schedule was a {type(absolute_schedules)}."
        assert isinstance(relative_schedules, (list, NoneType)), f"relative_schedule was a {type(relative_schedules)}."

        survey = Survey.create_with_object_id(study=study, **survey_settings)
        AbsoluteSchedule.create_absolute_schedules(absolute_schedules, survey)
        RelativeSchedule.create_relative_schedules(relative_schedules, survey)
        WeeklySchedule.create_weekly_schedules(weekly_schedules, survey)

        # count...
        surveys_added += 1 if survey.survey_type == Survey.TRACKING_SURVEY else 0
        audio_surveys_added += 1 if survey.survey_type == Survey.AUDIO_SURVEY else 0
        image_surveys_added += 1 if survey.survey_type == Survey.IMAGE_SURVEY else 0

    return "Copied %i Surveys and %i Audio Surveys from %s to %s." % \
           (surveys_added, audio_surveys_added, filename, study.name)
