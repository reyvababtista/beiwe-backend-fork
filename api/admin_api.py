from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http.request import HttpRequest
from django.http.response import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_GET, require_POST

from authentication.admin_authentication import (assert_admin, assert_researcher_under_admin,
    authenticate_admin, authenticate_researcher_login)
from config.settings import DOWNLOADABLE_APK_URL
from constants.message_strings import NEW_PASSWORD_N_LONG, PASSWORD_RESET_SITE_ADMIN
from constants.user_constants import ResearcherRole
from database.study_models import Study
from database.user_models_researcher import Researcher, StudyRelation
from libs.internal_types import ResearcherRequest
from libs.password_validation import check_password_requirements
from libs.schedules import repopulate_all_survey_scheduled_events
from libs.timezone_dropdown import ALL_TIMEZONES


"""######################### Study Administration ###########################"""


@require_POST
@authenticate_admin
def set_study_timezone(request: ResearcherRequest, study_id=None):
    """ Sets the custom timezone on a study. """
    new_timezone = request.POST.get("new_timezone_name")
    if new_timezone not in ALL_TIMEZONES:
        messages.warning(request, ("The timezone chosen does not exist."))
        return redirect(f'/edit_study/{study_id}')
    
    study = Study.objects.get(pk=study_id)
    study.timezone_name = new_timezone
    study.save()
    
    # All scheduled events for this study need to be recalculated
    # this causes chaos, relative and absolute surveys will be regenerated if already sent.
    repopulate_all_survey_scheduled_events(study)
    messages.warning(request, (f"Timezone {study.timezone_name} has been applied."))
    return redirect(f'/edit_study/{study_id}')


@require_POST
@authenticate_admin
def add_researcher_to_study(request: ResearcherRequest):
    researcher_id = request.POST['researcher_id']
    study_id = request.POST['study_id']
    assert_admin(request, study_id)
    try:
        StudyRelation.objects.get_or_create(
            study_id=study_id, researcher_id=researcher_id, relationship=ResearcherRole.researcher
        )
    except ValidationError:
        # handle case of the study id + researcher already existing
        pass
    
    # This gets called by both edit_researcher and edit_study, so the POST request
    # must contain which URL it came from.
    # TODO: don't source the url from the page, give it a required post parameter for the redirect and check against that
    return redirect(request.POST['redirect_url'])


@require_POST
@authenticate_admin
def remove_researcher_from_study(request: ResearcherRequest):
    researcher_id = request.POST['researcher_id']
    study_id = request.POST['study_id']
    try:
        researcher = Researcher.objects.get(pk=researcher_id)
    except Researcher.DoesNotExist:
        return HttpResponse(content="", status=404)
    assert_admin(request, study_id)
    assert_researcher_under_admin(request, researcher, study_id)
    StudyRelation.objects.filter(study_id=study_id, researcher_id=researcher_id).delete()
    # TODO: don't source the url from the page, give it a required post parameter for the redirect and check against that
    return redirect(request.POST['redirect_url'])


@require_GET
@authenticate_admin
def delete_researcher(request: ResearcherRequest, researcher_id):
    # only site admins can delete researchers from the system.
    if not request.session_researcher.site_admin:
        return HttpResponse(content="", status=403)
    researcher = get_object_or_404(Researcher, pk=researcher_id)
    
    StudyRelation.objects.filter(researcher=researcher).delete()
    researcher.delete()
    return redirect('/manage_researchers')


@require_POST
@authenticate_admin
def set_researcher_password(request: ResearcherRequest):
    """ This is the endpoint that an admin uses to set another researcher's password.
    This endpoint accepts any value as long as it is 8 characters, but puts the researcher into a
    forced password reset state. """
    researcher = Researcher.objects.get(pk=request.POST.get('researcher_id', None))
    assert_researcher_under_admin(request, researcher)
    if researcher.site_admin:
        messages.warning(request, PASSWORD_RESET_SITE_ADMIN)
        return redirect(f'/edit_researcher/{researcher.pk}')
    new_password = request.POST.get('password', '')
    if len(new_password) < 8:
        messages.warning(request, NEW_PASSWORD_N_LONG.format(length=8))
    else:
        researcher.set_password(new_password)
        researcher.update(password_force_reset=True)
    return redirect(f'/edit_researcher/{researcher.pk}')


@require_POST
@authenticate_admin
def rename_study(request: ResearcherRequest, study_id=None):
    study = Study.objects.get(pk=study_id)
    assert_admin(request, study_id)
    new_study_name = request.POST.get('new_study_name', '')
    study.name = new_study_name
    study.save()
    return redirect(f'/edit_study/{study.pk}')


@require_GET
@authenticate_admin
def toggle_easy_enrollment_study(request: ResearcherRequest, study_id: int):
    study = Study.objects.get(id=study_id)
    study.easy_enrollment = not study.easy_enrollment
    study.save()
    if study.easy_enrollment:
        messages.success(request, f'{study.name} now has Easy Enrollment enabled.')
    else:
        messages.success(request, f'{study.name} no longer has Easy Enrollment enabled.')
        manually_enabled = study.participants.filter(easy_enrollment=True).values_list("patient_id", flat=True)
        if manually_enabled:
            patient_ids = ", ".join(manually_enabled)
            messages.warning(
                request,
                 f"The following participants still have Easy Enrollment manually enabled: {patient_ids}"
            )
    return redirect(f'/edit_study/{study.pk}')



"""##### Methods responsible for distributing APK file of Android app. #####"""


def download_current(request: ResearcherRequest):
    return redirect(DOWNLOADABLE_APK_URL)


@authenticate_researcher_login
def download_current_debug(request: ResearcherRequest):
    return redirect("https://s3.amazonaws.com/beiwe-app-backups/release/Beiwe-debug.apk")


@authenticate_researcher_login
def download_beta(request: ResearcherRequest):
    return redirect("https://s3.amazonaws.com/beiwe-app-backups/release/Beiwe.apk")


@authenticate_researcher_login
def download_beta_debug(request: ResearcherRequest):
    return redirect("https://s3.amazonaws.com/beiwe-app-backups/debug/Beiwe-debug.apk")


@authenticate_researcher_login
def download_beta_release(request: ResearcherRequest):
    return redirect("https://s3.amazonaws.com/beiwe-app-backups/release/Beiwe-2.2.3-onnelaLabServer-release.apk")


def download_privacy_policy(request: HttpRequest):
    return redirect("https://s3.amazonaws.com/beiwe-app-backups/Beiwe+Data+Privacy+and+Security.pdf")
