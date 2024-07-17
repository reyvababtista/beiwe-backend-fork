import json
import random
from csv import writer
from re import sub

import bleach
from django.contrib import messages
from django.http.response import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from firebase_admin.exceptions import FirebaseError
from firebase_admin.messaging import (AndroidConfig, Message, Notification,
    send as send_push_notification, UnregisteredError)

from authentication.admin_authentication import authenticate_researcher_study_access
from constants.common_constants import API_TIME_FORMAT, RUNNING_TEST_OR_IN_A_SHELL
from constants.message_strings import (BAD_DEVICE_OS, BAD_PARTICIPANT_OS,
    DEVICE_HAS_NO_REGISTERED_TOKEN, MESSAGE_SEND_FAILED_PREFIX, MESSAGE_SEND_FAILED_UNKNOWN,
    MESSAGE_SEND_SUCCESS, NO_DELETION_PERMISSION, NOT_IN_STUDY, PARTICIPANT_RETIRED_SUCCESS,
    PUSH_NOTIFICATIONS_NOT_CONFIGURED, RESEND_CLICKED, SUCCESSFULLY_SENT_NOTIFICATION_PREFIX)
from constants.security_constants import OBJECT_ID_ALLOWED_CHARS
from constants.user_constants import ANDROID_API, DATA_DELETION_ALLOWED_RELATIONS, IOS_API
from database.schedule_models import ArchivedEvent, ScheduledEvent
from database.study_models import Study
from database.survey_models import Survey
from database.user_models_participant import Participant
from libs.firebase_config import check_firebase_instance
from libs.http_utils import easy_url
from libs.internal_types import ResearcherRequest
from libs.intervention_utils import add_fields_and_interventions
from libs.participant_purge import add_participant_for_deletion
from libs.s3 import create_client_key_pair, s3_upload
from libs.schedules import repopulate_all_survey_scheduled_events
from libs.sentry import make_error_sentry, SentryTypes
from libs.streaming_io import StreamingStringsIO


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
        add_participant_for_deletion(participant)
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


@require_POST
@authenticate_researcher_study_access
def resend_push_notification(request: ResearcherRequest, study_id: int, patient_id: str):
    """ Endpoint will resend a selected push notification.
    Note regarding refactoring: there are exactly 2 parts of the codebase (unless messaging has been
    merged that send push notifications: here, and celery push notification.  Due to the substantial
    variation of needing to handle response details these simple don't overlap much.  If and when
    messaging is merged in this should be revisited. """
    
    # 400 error if survey_id is not present
    survey_id = request.POST.get("survey_id", None)
    if not survey_id:
        return HttpResponse(content="", status=400)
    
    # oodles of setup, 404 cases for db queries, the redirect action...
    study = get_object_or_404(Study, pk=study_id)  # rejection should also be handled in decorator
    survey = get_object_or_404(Survey, pk=survey_id, deleted=False)
    participant = get_object_or_404(Participant, patient_id=patient_id, study=study)
    fcm_token = participant.get_valid_fcm_token()
    now = timezone.now()
    firebase_check_kwargs = {
        "require_android": participant.os_type == ANDROID_API,
        "require_ios": participant.os_type == IOS_API,
    }
    
    # setup exit details
    error_message = f'Could not send notification to {participant.patient_id}'
    return_redirect = redirect(
        "participant_pages.participant_page", study_id=study_id, patient_id=participant.patient_id
    )
    
    # create an event for this attempt, update it on all exit scenarios
    unscheduled_archive = ArchivedEvent(
        survey_archive=survey.most_recent_archive(),  # the current survey archive
        participant=participant,
        schedule_type=f"manual - {request.session_researcher.username}"[:32],  # max length of field
        scheduled_time=now,
        status=RESEND_CLICKED,
    )
    unscheduled_archive.save()
    
    # crete a scheduled event to point at, for records and checkin tracking.
    unscheduled_event = ScheduledEvent.objects.create(
        survey=survey,
        participant=participant,
        scheduled_time=now,
        most_recent_event=unscheduled_archive,
        deleted=True,  # don't continue to send this notification
    )
    
    # failures
    if fcm_token is None:
        unscheduled_archive.update(status=DEVICE_HAS_NO_REGISTERED_TOKEN)
        messages.error(request, error_message)
        return return_redirect
    
    # "participant os"
    if not check_firebase_instance(firebase_check_kwargs):
        unscheduled_archive.update(status=PUSH_NOTIFICATIONS_NOT_CONFIGURED)
        messages.error(request, error_message)
        return return_redirect
    
    data_kwargs = {
        'type': 'survey',
        'survey_ids': json.dumps([survey.object_id]),
        'sent_time': now.strftime(API_TIME_FORMAT),
        'nonce': ''.join(random.choice(OBJECT_ID_ALLOWED_CHARS) for _ in range(32)),
        'schedule_uuid': unscheduled_event.uuid or "",
    }
    
    if participant.os_type == ANDROID_API:
        message = Message(
            android=AndroidConfig(data=data_kwargs, priority='high'), token=fcm_token.token,
        )
    elif participant.os_type == IOS_API:
        message = Message(
            data=data_kwargs,
            token=fcm_token.token,
            notification=Notification(title="Beiwe", body="You have a survey to take."),
        )
    else:
        unscheduled_archive.update(status=f"{MESSAGE_SEND_FAILED_PREFIX} {BAD_DEVICE_OS}")
        messages.error(request, BAD_PARTICIPANT_OS)
        return return_redirect
    
    # real error cases (raised directly when running locally, reported to sentry on a server)
    try:
        _response = send_push_notification(message)
        unscheduled_archive.update(status=MESSAGE_SEND_SUCCESS)
        messages.success(
            request, f'{SUCCESSFULLY_SENT_NOTIFICATION_PREFIX} {participant.patient_id}.'
        )
    except (ValueError, FirebaseError, UnregisteredError) as e:
        # misconfiguration is not its own error type for some reason (and makes this code ugly)
        if isinstance(e, ValueError) and "The default Firebase app does not exist." not in str(e):
            unscheduled_archive.update(status=MESSAGE_SEND_FAILED_UNKNOWN + " (2)")  # presumably a bug
            messages.error(request, error_message)
            if not RUNNING_TEST_OR_IN_A_SHELL:
                with make_error_sentry(SentryTypes.elastic_beanstalk):
                    raise
        else:
            # normal case, firebase or unregistered error
            unscheduled_archive.update(status=f"Firebase Error, {MESSAGE_SEND_FAILED_PREFIX} {str(e)}")
            messages.error(request, error_message)
            # don't report unregistered
            if not RUNNING_TEST_OR_IN_A_SHELL and not isinstance(e, UnregisteredError):
                with make_error_sentry(SentryTypes.elastic_beanstalk):
                    raise
    except Exception:
        unscheduled_archive.update(status=MESSAGE_SEND_FAILED_UNKNOWN)  # presumably a bug
        messages.error(request, error_message)
        if not RUNNING_TEST_OR_IN_A_SHELL:
            with make_error_sentry(SentryTypes.elastic_beanstalk):
                raise
    return return_redirect
