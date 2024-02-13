from csv import writer
from re import sub

import bleach
from django.contrib import messages
from django.http.response import FileResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from authentication.admin_authentication import authenticate_researcher_study_access
from constants.message_strings import (NO_DELETION_PERMISSION, NOT_IN_STUDY,
    PARTICIPANT_RETIRED_SUCCESS)
from constants.user_constants import DATA_DELETION_ALLOWED_RELATIONS
from database.study_models import Study
from database.user_models_participant import Participant
from libs.http_utils import easy_url
from libs.internal_types import ResearcherRequest
from libs.intervention_utils import add_fields_and_interventions
from libs.participant_purge import add_particpiant_for_deletion
from libs.s3 import create_client_key_pair, s3_upload
from libs.schedules import repopulate_all_survey_scheduled_events
from libs.streaming_bytes_io import StreamingStringsIO


#FIXME: rename to participant_administration_api.py


@require_POST
@authenticate_researcher_study_access
def reset_participant_password(request: ResearcherRequest):
    """ Takes a patient ID and resets its password. Returns the new random password."""
    patient_id = request.POST.get('patient_id', None)
    study_id = request.POST.get('study_id', None)  # this is validated in the decorator
    participant_page = redirect(
        easy_url("participant_pages.participant_page", study_id=study_id, patient_id=patient_id)
    )
    
    try:
        participant = Participant.objects.get(patient_id=patient_id)
    except Participant.DoesNotExist:
        messages.error(request, f'The participant "{bleach.clean(patient_id)}" does not exist')
        return participant_page
    
    if participant.study.id != int(study_id):  # the standard not-in-study
        participant_not_in_study_message(request, patient_id, study_id)
        return participant_page
    
    if participant.is_dead:  # block locked participants, participant page already displays a message
        return participant_page
    
    new_password = participant.reset_password()
    messages.success(request, f'Patient {patient_id}\'s password has been reset to {new_password}.')
    return participant_page


@require_POST
@authenticate_researcher_study_access
def clear_device_id(request: ResearcherRequest):
    """ Resets a participant's device. The participant will not be able to connect until they
    register a new device. """
    patient_id = request.POST.get('patient_id', None)
    study_id = request.POST.get('study_id', None)
    participant_page = redirect(
        easy_url("participant_pages.participant_page", study_id=study_id, patient_id=patient_id)
    )
    
    try:
        participant = Participant.objects.get(patient_id=patient_id)
    except Participant.DoesNotExist:
        messages.error(request, f'The participant "{bleach.clean(patient_id)}" does not exist')
        return participant_page
    
    if participant.study.id != int(study_id):  # the standard not-in-study
        participant_not_in_study_message(request, patient_id, study_id)
        return participant_page
    
    if participant.is_dead:  # block locked participants, participant page already displays a message
        return participant_page
    
    participant.device_id = ""
    participant.save()
    messages.success(request, f'Participant {patient_id}\'s device status has been cleared.')
    return participant_page


@require_POST
@authenticate_researcher_study_access
def toggle_easy_enrollment(request: ResearcherRequest):
    """ Block participant from uploading further data """
    patient_id = request.POST.get('patient_id', None)
    study_id = request.POST.get('study_id', None)
    participant_page = redirect(
        easy_url("participant_pages.participant_page", study_id=study_id, patient_id=patient_id)
    )
    try:
        participant = Participant.objects.get(patient_id=patient_id)
    except Participant.DoesNotExist:
        messages.error(request, f'The participant "{bleach.clean(patient_id)}" does not exist')
        return participant_page
    
    if participant.study.id != int(study_id):  # the standard not-in-study
        participant_not_in_study_message(request, patient_id, study_id)
        return participant_page
    
    if participant.is_dead:  # block locked participants, participant page already displays a message
        return participant_page
    
    participant.easy_enrollment = not participant.easy_enrollment
    participant.save()
    if participant.easy_enrollment:
        messages.success(request, f'{patient_id} now has Easy Enrollment enabled.')
    else:
        messages.success(request, f'{patient_id} no longer has Easy Enrollment enabled.')
    return participant_page


@require_POST
@authenticate_researcher_study_access
def retire_participant(request: ResearcherRequest):
    """ Block participant from uploading further data """
    patient_id = request.POST.get('patient_id', None)
    study_id = request.POST.get('study_id', None)
    participant_page = redirect(
        easy_url("participant_pages.participant_page", study_id=study_id, patient_id=patient_id)
    )
    
    try:
        participant = Participant.objects.get(patient_id=patient_id)
    except Participant.DoesNotExist:
        messages.error(request, f'The participant "{bleach.clean(patient_id)}" does not exist')
        return participant_page  # okay that is wrong... I don't think we care though, just causes 404?
    
    if participant.study.id != int(study_id):  # the standard not-in-study
        participant_not_in_study_message(request, patient_id, study_id)
        return participant_page
    
    if participant.is_dead:  # block locked participants, participant page already displays a message
        return participant_page
    
    if participant.permanently_retired:
        messages.warning(request, f'Participant {patient_id} is already permanently retired.')
        return participant_page
    
    participant.permanently_retired = True
    participant.save()
    messages.error(request, PARTICIPANT_RETIRED_SUCCESS.format(patient_id=patient_id))
    return participant_page


@require_POST
@authenticate_researcher_study_access
def delete_participant(request: ResearcherRequest):
    """ Queues a participant for data purge. """
    patient_id = request.POST.get('patient_id', None)
    study_id = request.POST.get('study_id', None)
    participant_page = redirect(
        easy_url("participant_pages.participant_page", study_id=study_id, patient_id=patient_id)
    )
    
    try:
        participant = Participant.objects.get(patient_id=patient_id)
    except Participant.DoesNotExist:
        messages.error(request, f'The participant "{bleach.clean(patient_id)}" does not exist')
        return participant_page  # okay that is wrong... I don't think we care though, just causes 404?
    
    if participant.study.id != int(study_id):  # the standard not-in-study
        participant_not_in_study_message(request, patient_id, study_id)
        return participant_page
    
    if participant.is_dead:  # block locked participants, participant page already displays a message
        return participant_page
    
    relation = request.session_researcher.get_study_relation(study_id)
    if request.session_researcher.site_admin or relation in DATA_DELETION_ALLOWED_RELATIONS:
        add_particpiant_for_deletion(participant)
    else:
        messages.error(request, NO_DELETION_PERMISSION.format(patient_id=patient_id))
    return participant_page


@require_POST
@authenticate_researcher_study_access
def create_new_participant(request: ResearcherRequest):
    """ Creates a new user, generates a password and keys, pushes data to s3 and user database, adds
    user to the study they are supposed to be attached to and returns a string containing
    password and patient id. """
    
    study_id = request.POST.get('study_id', None)
    patient_id, password = Participant.create_with_password(study_id=study_id)
    participant = Participant.objects.get(patient_id=patient_id)
    study = Study.objects.get(id=study_id)
    add_fields_and_interventions(participant, study)
    
    # Create an empty file on S3 indicating that this user exists
    study_object_id = Study.objects.filter(pk=study_id).values_list('object_id', flat=True).get()
    s3_upload(patient_id, b"", study_object_id)
    create_client_key_pair(patient_id, study_object_id)
    repopulate_all_survey_scheduled_events(study, participant)
    
    messages.success(request, f'Created a new patient\npatient_id: {patient_id}\npassword: {password}')
    return redirect(f'/view_study/{study_id}')


@require_POST
@authenticate_researcher_study_access
def create_many_patients(request: ResearcherRequest, study_id=None):
    """ Creates a number of new users at once for a study.  Generates a password and keys for
    each one, pushes data to S3 and the user database, adds users to the study they're supposed
    to be attached to, and returns a CSV file for download with a mapping of Patient IDs and
    passwords. """
    number_of_new_patients = int(request.POST.get('number_of_new_patients', 0))
    desired_filename = request.POST.get('desired_filename', '')
    filename_spaces_to_underscores = sub(r'[\ =]', '_', desired_filename)
    filename = sub(r'[^a-zA-Z0-9_\.=]', '', filename_spaces_to_underscores)
    if not filename.endswith('.csv'):
        filename += ".csv"
    
    # for some reason we have to call set headers manually on FileResponse objects
    f = FileResponse(
        participant_csv_generator(study_id, number_of_new_patients),
        content_type="text/csv",
        as_attachment=True,
        filename=filename,
    )
    f.set_headers(None)
    return f


def participant_csv_generator(study_id, number_of_new_patients):
    study = Study.objects.get(pk=study_id)
    si = StreamingStringsIO()
    filewriter = writer(si)
    filewriter.writerow(['Patient ID', "Registration password"])
    
    for _ in range(number_of_new_patients):
        patient_id, password = Participant.create_with_password(study_id=study_id)
        participant = Participant.objects.get(patient_id=patient_id)
        add_fields_and_interventions(participant, Study.objects.get(id=study_id))
        # Creates an empty file on s3 indicating that this user exists
        s3_upload(patient_id, b"", study)
        create_client_key_pair(patient_id, study.object_id)
        repopulate_all_survey_scheduled_events(study, participant)
        
        filewriter.writerow([patient_id, password])
        yield si.getvalue()
        si.empty()


def participant_not_in_study_message(request: ResearcherRequest, patient_id: str, study_id: int):
    """ Standard message for a [maliciously?] mistargeted action on a participant the researcher
    does not have permissions for. """
    messages.error(
        request,
        NOT_IN_STUDY.format(patient_id=patient_id, study_name=Study.objects.get(id=study_id).name)
    )
