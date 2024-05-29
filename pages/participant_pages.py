from datetime import date, datetime, tzinfo
from itertools import chain
from typing import Dict

from django.contrib import messages
from django.core.paginator import EmptyPage, Paginator
from django.db.models import F
from django.http.response import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from api.participant_administration import add_fields_and_interventions
from authentication.admin_authentication import authenticate_researcher_study_access
from config.settings import ENABLE_EXPERIMENTS
from constants.action_log_messages import HEARTBEAT_PUSH_NOTIFICATION_SENT
from constants.common_constants import API_DATE_FORMAT, RUNNING_TEST_OR_IN_A_SHELL
from constants.message_strings import MESSAGE_SEND_SUCCESS, PARTICIPANT_LOCKED
from constants.user_constants import DATA_DELETION_ALLOWED_RELATIONS
from database.schedule_models import ArchivedEvent
from database.study_models import Study
from database.user_models_participant import Participant
from forms.django_forms import ParticipantExperimentForm
from libs.firebase_config import check_firebase_instance
from libs.http_utils import easy_url, nice_iso_time_format
from libs.internal_types import ArchivedEventQuerySet, ResearcherRequest
from libs.schedules import repopulate_all_survey_scheduled_events
from middleware.abort_middleware import abort


@require_GET
@authenticate_researcher_study_access
def notification_history(request: ResearcherRequest, study_id: int, patient_id: str):
    page_number = request.GET.get('page', 1)
    # blow up if the page number is not an integer or a (string) value that can be converted to an integer
    try:
        page_number = int(page_number)
    except ValueError:
        abort(400)
    
    # use the provided study id because authentication already validated it
    study = get_object_or_404(Study, pk=study_id) 
    participant = get_object_or_404(Participant, patient_id=patient_id)
    
    # defaults to false, looks for the string 'true'.
    include_keepalive = request.GET.get('include_keepalive', "false").lower() == 'true'
    
    # archived events are survey notification events, we have logic that expects page size of 25.
    archived_events = Paginator(query_values_for_notification_history(participant.id), 25)
    try:
        archived_events_page = archived_events.page(page_number)
    except EmptyPage:
        return HttpResponse(content="", status=404)
    last_page_number = archived_events.page_range.stop - 1
    
    if include_keepalive:
        # get the heartbeats that are relevant to this page
        heartbeats_query = get_heartbeats_query(participant, archived_events_page, page_number)
        # shove everything into one list.
        all_notifications = list(
            chain(archived_events_page, heartbeats_query.values_list("timestamp", flat=True))
        )
    else:
        all_notifications = list(archived_events_page)
    
    # Sort by the datetime objects we have, using a dictionary to detect (gross but we need to
    # interleave them) while we have datetime objects because we are using the super nice datetime
    # string formatting that is not sortable.
    all_notifications.sort(
        key=lambda list_or_dict: list_or_dict["created_on"] if isinstance(list_or_dict, dict) else list_or_dict,
        reverse=True,
    )
    
    # again based on object type we can determine which dictionaryifier to call, and we're done with
    # this INSANITY.
    notification_attempts = []
    survey_names = get_survey_names_dict(study)  # we need the survey names
    for notification in all_notifications:
        if isinstance(notification, dict):
            notification_attempts.append(
                notification_details_archived_event(notification, study.timezone, survey_names)
            )
        else:
            notification_attempts.append(
                notification_details_heartbeat(notification, study.timezone)
            )
    
    # and then the conditional message
    conditionally_display_locked_message(request, participant)
    return render(
        request,
        'notification_history.html',
        context=dict(
            participant=participant,
            page=archived_events_page,
            notification_attempts=notification_attempts,
            study=study,
            last_page_number=last_page_number,
            locked=participant.is_dead,
            include_keepalive=include_keepalive,
        )
    )


def get_heartbeats_query(participant: Participant, archived_events_page: Paginator, page_number: int):
    """ Using the elements in the archived pages, determine the bounds for the query of heartbeats,
    and then construct and return that query. """
    
    # tested, this does return the size of the page 
    count = archived_events_page.object_list.count()  
    
    if page_number == 1 and count < 25:
        # fewer than 25 notifications on the first page means that is all of them. So, get all the
        # heartbeats too. (this also detects and handles the case of zero total survey
        # notifications)
        heartbeat_query = participant.action_logs.filter(action=HEARTBEAT_PUSH_NOTIFICATION_SENT)
    elif page_number == 1 and count == 25:
        # if there are exactly 25 notifications on the first page then we want everything after
        # (greater than) the last notification on the page, no latest (most recent) bound).
        heartbeat_query = participant.action_logs.filter(
            timestamp__gte=archived_events_page[-1]["created_on"],
            action=HEARTBEAT_PUSH_NOTIFICATION_SENT
        )
    elif count < 25:
        # any non-full pages that are not the first page = get all heartbeats before the top (most
        # recent) notification on the page with no earliest (most in-the-past) bound.
        heartbeat_query = participant.action_logs.filter(
            timestamp__lte=archived_events_page[0]["created_on"],
            action=HEARTBEAT_PUSH_NOTIFICATION_SENT,
        )
    elif count == 25:
        # if there are exactly 25 notifications and we are not on the first page, then we bound it
        # by the first and last notifications... but that leaves out heartbeats between pages... but
        # that's both transient and rare? Solving this requires an extra queries and is hard so
        # unless someone complains we just will ignore this.
        # (we would need the date of the notification that came after the top (most recent)
        # notification in our list, and then use that as the upper (most recent) bound.)
        heartbeat_query = participant.action_logs.filter(
            action=HEARTBEAT_PUSH_NOTIFICATION_SENT,
            timestamp__range=(archived_events_page[0]["created_on"], archived_events_page[-1]["created_on"])
        )
    else:
        raise Exception("shouldn't that cover everything?")
    
    return heartbeat_query


@require_http_methods(['GET', 'POST'])
@authenticate_researcher_study_access
def participant_page(request: ResearcherRequest, study_id: int, patient_id: str):
    # use the provided study id because authentication already validated it
    participant = get_object_or_404(Participant, patient_id=patient_id)
    study = get_object_or_404(Study, pk=study_id)
    
    # safety check, enforce fields and interventions to be present for both page load and edit.
    if not participant.deleted or participant.has_deletion_event:
        add_fields_and_interventions(participant, study)
    
    # FIXME: get rid of dual endpoint pattern, it is a bad idea.
    if request.method == 'GET':
        return render_participant_page(request, participant, study)
    
    end_redirect = redirect(
        easy_url("participant_pages.participant_page", study_id=study_id, patient_id=patient_id)
    )
    
    # update intervention dates for participant
    for intervention in study.interventions.all():
        input_date = request.POST.get(f"intervention{intervention.id}", None)
        intervention_date = participant.intervention_dates.get(intervention=intervention)
        if input_date:
            try:
                intervention_date.update(date=datetime.strptime(input_date, API_DATE_FORMAT).date())
            except ValueError:
                messages.error(request, 'Invalid date format, please use the date selector or YYYY-MM-DD.')
                return end_redirect
    
    # update custom fields dates for participant
    for field in study.fields.all():
        input_id = f"field{field.id}"
        field_value = participant.field_values.get(field=field)
        field_value.update(value=request.POST.get(input_id, None))
    
    # always call through the repopulate everything call, even though we only need to handle
    # relative surveys, the function handles extra cases.
    repopulate_all_survey_scheduled_events(study, participant)
    
    messages.success(request, f'Successfully edited participant {participant.patient_id}.')
    return end_redirect


@authenticate_researcher_study_access
def experiments_page(request: ResearcherRequest, study_id: int, patient_id: str):
    if not ENABLE_EXPERIMENTS and not RUNNING_TEST_OR_IN_A_SHELL:
        raise Exception("YO EXPERIMENTS ARE DISABLED HOW IS THIS RUNNING 1")
    participant = get_object_or_404(Participant, patient_id=patient_id)
    # just render the page with the current state of the ParticipantExperimentForm.
    # page is almost nothing but that form.
    return render(
        request,
        'participant_experiments.html',
        context=dict(
            participant=participant,
            form=ParticipantExperimentForm(instance=participant),
        )
    )


@authenticate_researcher_study_access
def update_experiments(request: ResearcherRequest, study_id: int, patient_id: str):
    if not ENABLE_EXPERIMENTS and not RUNNING_TEST_OR_IN_A_SHELL:
        raise Exception("YO EXPERIMENTS ARE DISABLED HOW IS THIS RUNNING 2")
    # use the ParticipantExperimentForm to validate the input, update the participant
    # and then redirect back to the participant page.
    participant = get_object_or_404(Participant, patient_id=patient_id)
    
    form = ParticipantExperimentForm(request.POST)
    if form.is_valid():
        # form.save() doesn't tries to overwrite every field, which is stupid.
        participant.update(**form.cleaned_data)
        messages.success(request, f'Successfully updated participant {participant.patient_id}.')
    else:
        messages.error(request, 'Invalid form data, what are you doing?')
    return redirect(easy_url("participant_pages.participant_page", study_id=study_id, patient_id=patient_id))


def render_participant_page(request: ResearcherRequest, participant: Participant, study: Study):
    # to reduce database queries we get all the data across 4 queries and then merge it together.
    # dicts of intervention id to intervention date string, and of field names to value
    # (this was quite slow previously)
    intervention_dates_map = {
        # this is the intervention's id, not the intervention_date's id.
        intervention_id: format_date_or_none(intervention_date)
        for intervention_id, intervention_date in
        participant.intervention_dates.values_list("intervention_id", "date")
    }
    participant_fields_map = {
        name: value for name, value in
        participant.field_values.values_list("field__field_name", "value")
    }
    
    # list of tuples of (intervention id, intervention name, intervention date)
    intervention_data = [
        (intervention.id, intervention.name, intervention_dates_map.get(intervention.id, ""))
        for intervention in study.interventions.order_by("name")
    ]
    # list of tuples of field name, value.
    field_data = [
        (field_id, field_name, participant_fields_map.get(field_name, ""))
        for field_id, field_name
        in study.fields.order_by("field_name").values_list('id', "field_name")
    ]
    
    # dictionary structured for page rendering - we are not showing heartbeat notifications here.
    latest_notification_attempt = notification_details_archived_event(
        query_values_for_notification_history(participant.id).first(),
        study.timezone,
        get_survey_names_dict(study)
    )
    
    relation = request.session_researcher.get_study_relation(study.id)
    can_delete = request.session_researcher.site_admin or relation in DATA_DELETION_ALLOWED_RELATIONS
    
    conditionally_display_locked_message(request, participant)
    return render(
        request,
        'participant.html',
        context=dict(
            participant=participant,
            study=study,
            intervention_data=intervention_data,
            field_values=field_data,
            notification_attempts_count=participant.archived_events.count(),
            latest_notification_attempt=latest_notification_attempt,
            push_notifications_enabled_for_ios=check_firebase_instance(require_ios=True),
            push_notifications_enabled_for_android=check_firebase_instance(require_android=True),
            study_easy_enrollment=study.easy_enrollment,
            participant_easy_enrollment=participant.easy_enrollment,
            locked=participant.is_dead,
            can_delete=can_delete,
        )
    )


def query_values_for_notification_history(participant_id) -> ArchivedEventQuerySet:
    return (
        ArchivedEvent.objects
        .filter(participant_id=participant_id)
        .order_by('-created_on')
        .annotate(
            survey_id=F('survey_archive__survey'), survey_version=F('survey_archive__archive_start')
        )
        .values(
            'scheduled_time', 'created_on', 'survey_id', 'survey_version', 'schedule_type',
            'status', 'survey_archive__survey__deleted'
        )
    )


def get_survey_names_dict(study: Study):
    survey_names = {}
    for survey in study.surveys.all():
        if survey.name:
            survey_names[survey.id] = survey.name
        else:
            survey_names[survey.id] =\
                ("Audio Survey " if survey.survey_type == 'audio_survey' else "Survey ") + survey.object_id
    
    return survey_names


def notification_details_archived_event(
    archived_event: Dict, study_timezone: tzinfo, survey_names: Dict) -> Dict[str, str]:
    if archived_event is None:
        return {}
    return {
        'scheduled_time': nice_iso_time_format(archived_event['scheduled_time'], study_timezone),
        'attempted_time': nice_iso_time_format(archived_event['created_on'], study_timezone),
        'survey_name': survey_names[archived_event['survey_id']],
        'survey_id': archived_event['survey_id'],
        'survey_deleted': archived_event["survey_archive__survey__deleted"],
        'survey_version': archived_event['survey_version'].strftime('%Y-%m-%d'),
        'schedule_type': archived_event['schedule_type'],
        'status': archived_event['status'],
    }


def notification_details_heartbeat(
    heartbeat_timestamp: datetime, study_timezone: tzinfo) -> Dict[str, str]:
    return {
        'scheduled_time': "-",
        'attempted_time': nice_iso_time_format(heartbeat_timestamp, study_timezone),
        'survey_name': "-",
        'survey_id': "-",
        'survey_version': "-",
        'schedule_type': "Inactivity Notification",
        'status': MESSAGE_SEND_SUCCESS,
        # 'survey_deleted' # we don't actually need to include this.
    }


def format_date_or_none(d: date) -> str:
    # tiny function that broke scanability of the real code....
    return d.strftime(API_DATE_FORMAT) if isinstance(d, date) else ""


def conditionally_display_locked_message(request: ResearcherRequest, participant: Participant):
    """ Displays a warning message if the participant is locked. """
    if participant.is_dead:
        messages.warning(request, PARTICIPANT_LOCKED.format(patient_id=participant.patient_id))
