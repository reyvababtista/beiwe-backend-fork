from collections import defaultdict
from typing import Any, Dict

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import QuerySet

from database.study_models import DeviceSettings, Study
from database.survey_models import Survey
from libs.copy_study import copy_study_from_json, format_study, unpack_json_study
from libs.internal_types import ResearcherRequest


def get_administerable_studies_by_name(request: ResearcherRequest) -> QuerySet[Study]:
    """ Site admins see all studies, study admins see only studies they are admins on. """
    if request.session_researcher.site_admin:
        return Study.get_all_studies_by_name()
    else:
        return request.session_researcher.get_administered_studies_by_name()


def unflatten_consent_sections(consent_sections_dict: dict):
    # consent_sections is a flat structure with structure like this:
    # { 'label_ending_in.text': 'text content',  'label_ending_in.more': 'more content' }
    # we need to transform it into a nested structure like this:
    # { 'label': {'text':'text content',  'more':'more content' }
    refactored_consent_sections = defaultdict(dict)
    for key, content in consent_sections_dict.items():
        _, label, content_type = key.split(".")
        refactored_consent_sections[label][content_type] = content
    return dict(refactored_consent_sections)


"""########################### Study Pages ##################################"""

def do_duplicate_step(request: ResearcherRequest, new_study: Study):
    """ Everything you need to copy a study. """
    # surveys are always provided, there is a checkbox about whether to import them
    copy_device_settings = request.POST.get('device_settings', None) == 'true'
    copy_surveys = request.POST.get('surveys', None) == 'true'
    old_study = Study.objects.get(pk=request.POST.get('existing_study_id', None))
    device_settings, surveys, interventions = unpack_json_study(format_study(old_study))
    
    copy_study_from_json(
        new_study,
        device_settings if copy_device_settings else {},
        surveys if copy_surveys else [],
        interventions,
    )
    tracking_surveys_added = new_study.surveys.filter(survey_type=Survey.TRACKING_SURVEY).count()
    audio_surveys_added = new_study.surveys.filter(survey_type=Survey.AUDIO_SURVEY).count()
    messages.success(
        request,
        f"Copied {tracking_surveys_added} Surveys and {audio_surveys_added} "
        f"Audio Surveys from {old_study.name} to {new_study.name}.",
    )
    if copy_device_settings:
        messages.success(
            request, f"Overwrote {new_study.name}'s App Settings with custom values."
        )
    else:
        messages.success(request, f"Did not alter {new_study.name}'s App Settings.")


def try_update_device_settings(request: ResearcherRequest, params: Dict[str, Any], study: Study):
    # attempts to update, backs off if there were any failures, notifies users of bad fields.
    # (finally a situation where django forms would be better, sorta, I don't think it allows
    # partial updates without mucking around.)
    try:
        study.device_settings.update(**params)
    except ValidationError as validation_errors:
        old_device_settings = DeviceSettings.objects.get(study=study)
        
        # ValidationError.message_dict is the least obtuse way to do this
        for field, field_messages in validation_errors.message_dict.items():
            # remove new value from device settings (ugly, whatever)
            setattr(study.device_settings, field, getattr(old_device_settings, field))
            for msg in field_messages:
                messages.error(request, f"{field.replace('_', ' ').title()} wos NOT updated, '{msg}'")
        
        # save without the bad fields
        study.device_settings.save()


def trim_whitespace(request: ResearcherRequest, params: Dict[str, Any], notify: bool = False):
    """ trims whitespace from all dictionary values """
    for k, v in params.items():
        if isinstance(v, str):
            v_trimmed = v.strip()
            if v_trimmed != v:
                params[k] = v_trimmed
                if notify:
                    messages.info(request, message=f"whitespace was trimmed on {k.replace('_', ' ')}")


def notify_changes(
    request: ResearcherRequest, params: Dict[str, Any], comparee: Dict[str, Any], message_prefix: str = ""
):
    """ Determines differences between 2 dictionaries and notifies the user based on key name values. """
    # convert to string to compare value representations (assumes type conversion is already handled)
    updated = [k.replace("_", " ").title() for k, v in params.items() if str(comparee[k]) != str(v)]
    updated.sort()
    if len(updated) == 1:
        messages.info(request, message_prefix + f"{updated[0]} was updated.")
    elif len(updated) > 1:
        start, end = f"{', '.join(updated)} were all updated.".rsplit(",", 1)
        end = ", and" + end
        messages.info(request, message_prefix + start + end)
