from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from authentication.admin_authentication import (assert_site_admin, authenticate_admin,
    authenticate_researcher_login, authenticate_researcher_study_access,
    get_researcher_allowed_studies_as_query_set)
from constants.common_constants import DISPLAY_TIME_FORMAT
from constants.user_constants import ResearcherRole
from database.data_access_models import FileToProcess
from database.study_models import Study
from database.user_models_researcher import Researcher, StudyRelation
from forms.django_forms import StudyEndDateForm
from libs.firebase_config import check_firebase_instance
from libs.internal_types import ResearcherRequest
from libs.timezone_dropdown import ALL_TIMEZONES_DROPDOWN
from pages.admin_pages import conditionally_display_study_status_warnings
from pages.system_admin_pages import (get_administerable_researchers,
    get_administerable_studies_by_name)


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
