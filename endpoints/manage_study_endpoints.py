
from django.contrib import messages
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_POST

from authentication.admin_authentication import assert_admin, authenticate_admin
from database.study_models import Study
from libs.internal_types import ResearcherRequest
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
