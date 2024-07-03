import json

import bleach
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from markupsafe import escape

from authentication.admin_authentication import (abort, assert_admin, assert_site_admin,
    authenticate_admin, authenticate_researcher_login, authenticate_researcher_study_access,
    get_researcher_allowed_studies_as_query_set)
from constants.common_constants import DISPLAY_TIME_FORMAT, RUNNING_TEST_OR_IN_A_SHELL
from constants.html_constants import CHECKBOX_TOGGLES, TIMER_VALUES
from constants.user_constants import ResearcherRole
from database.data_access_models import FileToProcess
from database.study_models import Study
from database.user_models_researcher import Researcher, StudyRelation
from forms.django_forms import StudyEndDateForm, StudySecuritySettingsForm
from libs.endpoint_helpers.researcher_helpers import get_administerable_researchers
from libs.endpoint_helpers.study_helpers import (get_administerable_studies_by_name, notify_changes, trim_whitespace, try_update_device_settings,
    unflatten_consent_sections)
from libs.firebase_config import check_firebase_instance
from libs.http_utils import checkbox_to_boolean, easy_url, string_to_int
from libs.internal_types import ResearcherRequest
from libs.password_validation import get_min_password_requirement
from libs.sentry import make_error_sentry, SentryTypes
from libs.timezone_dropdown import ALL_TIMEZONES_DROPDOWN
from pages.admin_pages import conditionally_display_study_status_warnings


@require_GET
@authenticate_researcher_login
def choose_study_page(request: ResearcherRequest):
    allowed_studies = get_researcher_allowed_studies_as_query_set(request)
    # If the admin is authorized to view exactly 1 study, redirect to that study,
    # Otherwise, show the "Choose Study" page
    if allowed_studies.count() == 1:
        return redirect('/view_study/{:d}'.format(allowed_studies.values_list('pk', flat=True).get()))
    
    return render(
        request,
        'choose_study.html',
        context=dict(
            studies=list(allowed_studies.values("name", "id")),
            is_admin=request.session_researcher.is_an_admin(),
        )
    )


@require_GET
@authenticate_researcher_study_access
def view_study_page(request: ResearcherRequest, study_id=None):
    study: Study = Study.objects.get(pk=study_id)
    
    def get_survey_info(survey_type: str):
        survey_info = list(
            study.surveys.filter(survey_type=survey_type, deleted=False)
            .values('id', 'object_id', 'name', "last_updated")
        )
        for info in survey_info:
            info["last_updated"] = \
                 info["last_updated"].astimezone(study.timezone).strftime(DISPLAY_TIME_FORMAT)
        return survey_info
    
    is_study_admin = StudyRelation.objects.filter(
        researcher=request.session_researcher, study=study, relationship=ResearcherRole.study_admin
    ).exists()
    
    conditionally_display_study_status_warnings(request, study)
    
    return render(
        request,
        template_name='view_study.html',
        context=dict(
            study=study,
            participants_ever_registered_count=study.participants.exclude(os_type='').count(),
            audio_survey_info=get_survey_info('audio_survey'),
            tracking_survey_info=get_survey_info('tracking_survey'),
            # these need to be lists because they will be converted to json.
            study_fields=list(study.fields.all().values_list('field_name', flat=True)),
            interventions=list(study.interventions.all().values_list("name", flat=True)),
            page_location='view_study',
            study_id=study_id,
            is_study_admin=is_study_admin,
            push_notifications_enabled=check_firebase_instance(require_android=True) or
                                       check_firebase_instance(require_ios=True),
        )
    )


@require_GET
@authenticate_admin
def manage_studies(request: ResearcherRequest):
    return render(
        request,
        'manage_studies.html',
        context=dict(
            studies=list(get_administerable_studies_by_name(request).values("id", "name")),
            unprocessed_files_count=FileToProcess.objects.count(),
        )
    )


@require_GET
@authenticate_admin
def edit_study(request, study_id=None):
    study = Study.objects.get(pk=study_id)  # already validated by the decorator
    
    # get the data points for display for all researchers in this study
    query = Researcher.filter_alphabetical(study_relations__study_id=study_id).values_list(
        "id", "username", "study_relations__relationship", "site_admin"
    )
    
    # transform raw query data as needed
    listed_researchers = []
    for pk, username, relationship, site_admin in query:
        listed_researchers.append((
            pk,
            username,
            "Site Admin" if site_admin else relationship.replace("_", " ").title(),
            site_admin
        ))
    
    conditionally_display_study_status_warnings(request, study)
    
    return render(
        request,
        'edit_study.html',
        context=dict(
            study=study,
            administerable_researchers=get_administerable_researchers(request),
            listed_researchers=listed_researchers,
            redirect_url=f'/edit_study/{study_id}',
            timezones=ALL_TIMEZONES_DROPDOWN,
            page_location="edit_study",
        )
    )


@require_POST
@authenticate_admin
def update_end_date(request: ResearcherRequest, study_id=None):
    assert_site_admin(request)
    study = Study.objects.get(pk=study_id)  # already validated by the decorator
    
    if "end_date" not in request.POST:
        messages.error(request, "No date provided.")
        return redirect("study_endpoints.edit_study", study_id=study.id)
    
    form = StudyEndDateForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Invalid date format, expected YYYY-MM-DD.")
        return redirect("study_endpoints.edit_study", study_id=study.id)
    
    study.end_date = form.cleaned_data["end_date"]
    study.save()
    
    if study.end_date:
        messages.success(
            request,
            f"Study '{study.name}' has had its End Date updated to {study.end_date.isoformat()}."
        )
    else:
        messages.success(request, f"Study '{study.name}' has had its End Date removed.")
    
    return redirect("study_endpoints.edit_study", study_id=study.id)


@require_POST
@authenticate_admin
def toggle_end_study(request: ResearcherRequest, study_id=None):
    assert_site_admin(request)
    study = Study.objects.get(pk=study_id)  # already validated by the decorator
    
    study.manually_stopped = not study.manually_stopped
    study.save()
    if study.manually_stopped:
        messages.success(request, f"Study '{study.name}' has been manually stopped.")
    else:
        messages.success(request, f"Study '{study.name}' has been manually re-opened.")
    
    return redirect("study_endpoints.edit_study", study_id=study.id)


@require_http_methods(['GET', 'POST'])
@authenticate_admin
def create_study(request: ResearcherRequest):
    # Only a SITE admin can create new studies.
    if not request.session_researcher.site_admin:
        return abort(403)
    
    # FIXME: get rid of dual endpoint pattern, it is a bad idea.
    
    if request.method == 'GET':
        studies = list(Study.get_all_studies_by_name().values("name", "id"))
        return render(request, 'create_study.html', context=dict(studies=studies))
    
    name = request.POST.get('name', '')
    encryption_key = request.POST.get('encryption_key', '')
    duplicate_existing_study = request.POST.get('copy_existing_study', None) == 'true'
    forest_enabled = request.POST.get('forest_enabled', "").lower() == 'true'
    
    if len(name) > 5000:
        if not RUNNING_TEST_OR_IN_A_SHELL:
            with make_error_sentry(SentryTypes.elastic_beanstalk):
                raise Exception("Someone tried to create a study with a suspiciously long name.")
        messages.error(request, 'the study name you provided was too long and was rejected, please try again.')
        return redirect('/create_study')
    
    if escape(name) != name:
        if not RUNNING_TEST_OR_IN_A_SHELL:
            with make_error_sentry(SentryTypes.elastic_beanstalk):
                raise Exception("Someone tried to create a study with unsafe characters in its name.")
        messages.error(request, 'the study name you provided contained unsafe characters and was rejected, please try again.')
        return redirect('/create_study')
    
    try:
        new_study = Study.create_with_object_id(
            name=name, encryption_key=encryption_key, forest_enabled=forest_enabled
        )
        if duplicate_existing_study:
            do_duplicate_step(request, new_study)
        messages.success(request, f'Successfully created study {name}.')
        return redirect(f'/device_settings/{new_study.pk}')
    
    except ValidationError as ve:
        # display message describing failure based on the validation error (hacky, but works.)
        for field, message in ve.message_dict.items():
            messages.error(request, f'{field}: {message[0]}')
        return redirect('/create_study')


@require_POST
@authenticate_admin
def hide_study(request: ResearcherRequest, study_id=None):
    # Site admins and study admins can delete studies.
    assert_site_admin(request)
    
    if request.POST.get('confirmation', 'false') == 'true':
        study = Study.objects.get(pk=study_id)
        study.manually_stopped = True
        study.deleted = True
        study.save()
        study_name = bleach.clean(study.name)  # very redundant
        messages.success(request, f"Study '{study_name}' has been hidden.")
    else:
        abort(400)
    
    return redirect("study_endpoints.manage_studies")


@require_GET
@authenticate_admin
def study_security_page(request: ResearcherRequest, study_id: int):
    study = Study.objects.get(id=study_id)
    assert_admin(request, study_id)
    return render(
        request,
        'study_security_settings.html',
        context=dict(
            study=study,
            min_password_length=get_min_password_requirement(request.session_researcher),
        )
    )


@require_POST
@authenticate_admin
def change_study_security_settings(request: ResearcherRequest, study_id=None):
    study = Study.objects.get(pk=study_id)
    assert_admin(request, study_id)
    nice_names = {
        "password_minimum_length": "Minimum Password Length",
        "password_max_age_enabled": "Enable Maximum Password Age",
        "password_max_age_days": "Maximum Password Age (days)",
        "mfa_required": "Require Multi-Factor Authentication",
    }
    
    form = StudySecuritySettingsForm(request.POST, instance=study)
    if not form.is_valid():
        # extract errors from the django form and display them using django messages
        for field, errors in form.errors.items():
            for error in errors:
                # make field names nicer for the error message
                messages.warning(request, f"{nice_names.get(field, field)}: {error}")
        return redirect(easy_url("study_endpoints.study_security_page", study_id=study.pk))
    
    # success: save and display changes, redirect to edit study
    form.save()
    for field_name in form.changed_data:
        messages.success(
            request, f"Updated {nice_names.get(field_name, field_name)} to {getattr(study, field_name)}"
        )
    return redirect(easy_url("study_endpoints.edit_study", study.pk))


@require_http_methods(['GET', 'POST'])
@authenticate_researcher_study_access
def device_settings(request: ResearcherRequest, study_id=None):
    # TODO: probably rewrite this entire endpoint with django forms....
    study = Study.objects.get(pk=study_id)
    researcher = request.session_researcher
    readonly = not researcher.check_study_admin(study_id) and not researcher.site_admin
    
    # FIXME: get rid of dual endpoint pattern, it is a bad idea.
    if request.method == 'GET':
        conditionally_display_study_status_warnings(request, study)
        return render(
            request,
            "study_device_settings.html",
            context=dict(
                study=study.as_unpacked_native_python(Study.STUDY_EXPORT_FIELDS),
                settings=study.device_settings.export(),
                readonly=readonly,
            )
        )
    if readonly:
        abort(403)
    
    # the ios consent sections are a json field but the frontend returns something weird,
    # see the documentation in unflatten_consent_sections for details
    consent_sections = unflatten_consent_sections(
        {k: v for k, v in request.POST.items() if k.startswith("consent_section")}
    )
    params = {
        k: v for k, v in request.POST.items()
        if not k.startswith("consent_section") and hasattr(study.device_settings, k)
    }
    
    # numerous data fixes
    checkbox_to_boolean(CHECKBOX_TOGGLES, params)
    string_to_int(TIMER_VALUES, params)
    trim_whitespace(request, params)  # there's a frontend bug where whitespace can get inserted.
    trim_whitespace(request, consent_sections)
    
    # logic to display changes to the user
    notify_changes(request, params, study.device_settings.as_dict(), "Settings for ")
    try:
        # can't be 100% sure that this data is safe to deserialize
        current_consents = json.loads(study.device_settings.consent_sections)
        notify_changes(request, consent_sections, current_consents, "iOS Consent Section ")
    except json.JSONDecodeError:
        pass
    
    # final params setup, attempt db update, redirect to edit study page
    params["consent_sections"] = json.dumps(consent_sections)
    try_update_device_settings(request, params, study)
    return redirect(f'/edit_study/{study.id}')


# FIXME: this should take a post parameter, not a url endpoint.
@require_POST
@authenticate_admin
def toggle_study_forest_enabled(request: ResearcherRequest, study_id=None):
    # Only a SITE admin can toggle forest on a study
    if not request.session_researcher.site_admin:
        return abort(403)
    study = Study.objects.get(pk=study_id)
    study.forest_enabled = not study.forest_enabled
    study.save()
    if study.forest_enabled:
        messages.success(request, f"Enabled Forest on '{study.name}'")
    else:
        messages.success(request, f"Disabled Forest on '{study.name}'")
    return redirect(f'/edit_study/{study_id}')
