import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta
from io import StringIO
from typing import Dict, Optional, Union

from django.contrib import messages
from django.db.models import ProtectedError
from django.db.models.expressions import ExpressionWrapper
from django.db.models.fields import BooleanField
from django.db.models.functions.text import Lower
from django.db.models.query_utils import Q
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from authentication.admin_authentication import authenticate_researcher_study_access
from constants.common_constants import API_DATE_FORMAT
from database.schedule_models import Intervention, InterventionDate
from database.study_models import Study, StudyField
from database.user_models_participant import Participant, ParticipantFieldValue
from libs.internal_types import ParticipantQuerySet, ResearcherRequest
from libs.intervention_utils import (correct_bad_interventions, intervention_survey_data,
    survey_history_export)


@require_POST
@authenticate_researcher_study_access
def study_participants_api(request: ResearcherRequest, study_id: int):
    study: Study = Study.objects.get(pk=study_id)
    correct_bad_interventions(study)
    
    # `draw` is passed by DataTables. It's automatically incremented, starting with 1 on the page
    # load, and then 2 with the next call to this API endpoint, and so on.
    draw = int(request.POST.get('draw'))
    start = int(request.POST.get('start'))
    length = int(request.POST.get('length'))
    sort_by_column_index = int(request.POST.get('order[0][column]'))
    sort_in_descending_order = request.POST.get('order[0][dir]') == 'desc'
    contains_string = request.POST.get('search[value]')
    total_participants_count = Participant.objects.filter(study_id=study_id).count()
    filtered_participants_count = filtered_participants(study, contains_string).count()
    data = get_values_for_participants_table(
        study, start, length, sort_by_column_index, sort_in_descending_order, contains_string
    )
    
    table_data = {
        "draw": draw,
        "recordsTotal": total_participants_count,
        "recordsFiltered": filtered_participants_count,
        "data": data
    }
    return JsonResponse(table_data, status=200)


@require_http_methods(['GET', 'POST'])
@authenticate_researcher_study_access
def download_participants_csv(request: ResearcherRequest, study_id: int = None):
    """ Download a CSV file version of the participants table on the view study page. """
    study: Study = Study.objects.get(pk=study_id)  # already validated by the decorator.
    
    total_participants = Participant.objects.filter(study_id=study_id).count()
    data = get_values_for_participants_table(
        study=study,
        start=0,
        length=total_participants,
        sort_by_column_index=1,  # sort by patient_id
        sort_in_descending_order=False,  
        contains_string="",
    )
    
    # we need to get the field names and intervention names as they are displayed on the page
    study_fields = list(study.fields.all().values_list('field_name', flat=True))
    interventions = list(study.interventions.all().values_list("name", flat=True))
    
    # sort is defined as lower case, interventions then fields
    interventions.sort(key=lambda x: x.lower())
    study_fields.sort(key=lambda x: x.lower())
    header_row = ["Created On", "Patient ID", "Status", "OS Type"] + interventions + study_fields
    
    # we need to write the data to a buffer, and then return the buffer as a response
    buffer = StringIO()
    writer = csv.writer(buffer, dialect="excel")
    writer.writerow(header_row)
    writer.writerows(data)
    buffer.seek(0)
    return HttpResponse(buffer.read(), content_type='text/csv')




@require_http_methods(['GET', 'POST'])
@authenticate_researcher_study_access
def interventions_page(request: ResearcherRequest, study_id=None):
    study: Study = Study.objects.get(pk=study_id)
    # TODO: get rid of dual endpoint pattern, it is a bad idea.
    if request.method == 'GET':
        return render(
            request,
            'study_interventions.html',
            context=dict(
                study=study,
                interventions=study.interventions.all(),
            ),
        )
    
    # slow but safe
    new_intervention = request.POST.get('new_intervention', None)
    if new_intervention:
        intervention, _ = Intervention.objects.get_or_create(study=study, name=new_intervention)
        for participant in study.participants.all():
            InterventionDate.objects.get_or_create(participant=participant, intervention=intervention)
    
    return redirect(f'/interventions/{study.id}')


@require_http_methods(['GET', 'POST'])
@authenticate_researcher_study_access
def download_study_interventions(request: ResearcherRequest, study_id=None):
    study = get_object_or_404(Study, id=study_id)
    data = intervention_survey_data(study)
    fr = FileResponse(
        json.dumps(data),
        content_type="text/json",
        as_attachment=True,
        filename=f"{study.object_id}_intervention_data.json",
    )
    fr.set_headers(None)  # django is kinda stupid? buh?
    return fr


@require_http_methods(['GET', 'POST'])
@authenticate_researcher_study_access
def download_study_survey_history(request: ResearcherRequest, study_id=None):
    study = get_object_or_404(Study, id=study_id)
    fr = FileResponse(
        survey_history_export(study).decode(),  # okay, whatever, it needs to be a string, not bytes
        content_type="text/json",
        as_attachment=True,
        filename=f"{study.object_id}_surveys_history_data.json",
    )
    fr.set_headers(None)  # django is still stupid?
    return fr


@require_POST
@authenticate_researcher_study_access
def delete_intervention(request: ResearcherRequest, study_id=None):
    """Deletes the specified Intervention. Expects intervention in the request body."""
    study = Study.objects.get(pk=study_id)
    intervention_id = request.POST.get('intervention')
    if intervention_id:
        try:
            intervention = Intervention.objects.get(id=intervention_id)
        except Intervention.DoesNotExist:
            intervention = None
        try:
            if intervention:
                intervention.delete()
        except ProtectedError:
            messages.warning("This Intervention can not be removed because it is already in use")
    
    return redirect(f'/interventions/{study.id}')


@require_POST
@authenticate_researcher_study_access
def edit_intervention(request: ResearcherRequest, study_id=None):
    """ Edits the name of the intervention. Expects intervention_id and edit_intervention in the
    request body """
    study = Study.objects.get(pk=study_id)
    intervention_id = request.POST.get('intervention_id', None)
    new_name = request.POST.get('edit_intervention', None)
    if intervention_id:
        try:
            intervention = Intervention.objects.get(id=intervention_id)
        except Intervention.DoesNotExist:
            intervention = None
        if intervention and new_name:
            intervention.name = new_name
            intervention.save()
    
    return redirect(f'/interventions/{study.id}')


@require_http_methods(['GET', 'POST'])
@authenticate_researcher_study_access
def study_fields(request: ResearcherRequest, study_id=None):
    study = Study.objects.get(pk=study_id)
    # TODO: get rid of dual endpoint pattern, it is a bad idea.
    if request.method == 'GET':
        return render(
            request,
            'study_custom_fields.html',
            context=dict(
                study=study,
                fields=study.fields.all(),
            ),
        )
    
    new_field = request.POST.get('new_field', None)
    if new_field:
        study_field, _ = StudyField.objects.get_or_create(study=study, field_name=new_field)
        for participant in study.participants.all():
            ParticipantFieldValue.objects.create(participant=participant, field=study_field)
    
    return redirect(f'/study_fields/{study.id}')


@require_POST
@authenticate_researcher_study_access
def delete_field(request: ResearcherRequest, study_id=None):
    """Deletes the specified Custom Field. Expects field in the request body."""
    study = Study.objects.get(pk=study_id)
    field = request.POST.get('field', None)
    if field:
        try:
            study_field = StudyField.objects.get(study=study, id=field)
        except StudyField.DoesNotExist:
            study_field = None
        
        try:
            if study_field:
                study_field.delete()
        except ProtectedError:
            messages.warning("This field can not be removed because it is already in use")
    
    return redirect(f'/study_fields/{study.id}')


@require_POST
@authenticate_researcher_study_access
def edit_custom_field(request: ResearcherRequest, study_id=None):
    """Edits the name of a Custom field. Expects field_id anf edit_custom_field in request body"""
    field_id = request.POST.get("field_id")
    new_field_name = request.POST.get("edit_custom_field")
    if field_id:
        try:
            field = StudyField.objects.get(id=field_id)
        except StudyField.DoesNotExist:
            field = None
        if field and new_field_name:
            field.field_name = new_field_name
            field.save()
    
    # this apparent insanity is a hopefully unnecessary confirmation of the study id
    return redirect(f'/study_fields/{Study.objects.get(pk=study_id).id}')


THE_QUERY_FIELDS = (
    "id",
    "created_on",
    "patient_id",
    "registered",
    "os_type",
    "last_upload",
    "last_get_latest_surveys",
    "last_set_password",
    "last_set_fcm_token",
    "last_get_latest_device_settings",
    "last_register_user",
)

def get_values_for_participants_table(
    study: Study, start: int, length: int, sort_by_column_index: int,
    sort_in_descending_order: bool, contains_string: str
):
    """ Logic to get paginated information of the participant list on a study.
    This code used to be horrible - e.g. it committed the unforgivable sin of trying to speed up
    complex query logic with prefetch_related. It has been rewritten in ugly but performant and
    comprehensible values_list code that emits a total of 4 queries. This is literally a hundred
    times faster, even though it always has to pull in all the study participants.
    
    Example extremely simple study output, no fields or interventions, no sorting or filtering
    parameters were applied:
    [['2021-12-09', '1f9qb91f', 'Inactive', 'ANDROID'],
    ['2021-03-18', 'bnhyxqey', 'Inactive', 'ANDROID'],
    ['2022-09-27', 'c3b7mk7j', 'Inactive', 'IOS'],
    ['2021-12-09', 'e1yjh259', 'Inactive', 'IOS'],
    ['2022-06-23', 'ksg8clpo', 'Inactive', 'IOS'],
    ['2018-04-12', 'prx7ap5x', 'Inactive', 'ANDROID'],
    ['2018-04-12', 'whr8nx5b', 'Inactive', 'IOS']]
    """
    # ~ is the not operator - this might or might not speed up the query, whatever.
    HAS_NO_DEVICE_ID = ExpressionWrapper(~Q(device_id=''), output_field=BooleanField())
    
    # we need a reference list of all field and intervention names names ordered to match the
    # ordering on the rendering page. Order is lowercase alphanumerical.
    field_names_ordered = list(
        study.fields.values_list("field_name", flat=True).order_by(Lower('field_name'))
    )
    intervention_names_ordered = list(
        study.interventions.values_list("name", flat=True).order_by(Lower('name'))
    )
    
    # set up the big participant query and get our lookup dicts of field values and interventions
    query = filtered_participants(study, contains_string)
    query = query.annotate(registered=HAS_NO_DEVICE_ID)
    fields_lookup, interventions_lookup = get_interventions_and_fields(query)
    
    # set the time for determining status, and get the values for all participants
    now = timezone.now()
    all_participants_data = []
    for (
        p_id, created_on, patient_id, registered, os_type, last_upload, last_get_latest_surveys,
        last_set_password, last_set_fcm_token, last_get_latest_device_settings, last_register_user
    ) in query.values_list(*THE_QUERY_FIELDS):
        created_on = created_on.strftime(API_DATE_FORMAT)
        participant_values = [created_on, patient_id, registered, os_type]
        
        # We can't trivially optimize this out because we need to be able to sort across all study
        # participants on the status column. It probably is possible to grab the lowest value of all
        # the timestamps inside the query, and then order_by on that inside the query... but have to
        # fill empty StudyFields with Nones in there somehow too, and there are comments here about
        # encountering a django bug. (Since python 3.8 shifted datetimes to structs the performance
        # concern here is substantially lessened. Also values_list is seriously fast.)
        participant_values[2] = determine_registered_status(
            now, registered, last_upload, last_get_latest_surveys, last_set_password,
            last_set_fcm_token, last_get_latest_device_settings, last_register_user
        )
        
        # intervention dates are guaranteed to be present
        for int_name in intervention_names_ordered:
            int_date: datetime = interventions_lookup[p_id][int_name]
            participant_values.append(int_date.strftime(API_DATE_FORMAT) if int_date else "")
        # but field values are not
        for field_name in field_names_ordered:
            if field_name in fields_lookup[p_id]:
                field_value = fields_lookup[p_id][field_name]
                participant_values.append(field_value if field_value else "")
            else:
                participant_values.append("")
        
        all_participants_data.append(participant_values)
    
    # guarantees: all rows have the same number of columns, all values are strings.
    # if sort_by_column_index >= len(BASIC_COLUMNS):
    all_participants_data.sort(key=lambda row: row[sort_by_column_index], reverse=sort_in_descending_order)
    all_participants_data = all_participants_data[start:start + length]
    return all_participants_data


def filtered_participants(study: Study, contains_string: str):
    """ Searches for participants with lowercase matches on os_type and patient_id, excludes deleted participants. """
    return Participant.objects.filter(study_id=study.id) \
            .filter(Q(patient_id__icontains=contains_string) | Q(os_type__icontains=contains_string)) \
            .exclude(deleted=True)


def determine_registered_status(
    now: datetime,
    registered: bool,
    last_upload: Optional[datetime],
    last_get_latest_surveys: Optional[datetime],
    last_set_password: Optional[datetime],
    last_set_fcm_token: Optional[datetime],
    last_get_latest_device_settings: Optional[datetime],
    last_register_user: Optional[datetime],
):
    """ Provides a very simple string for whether this participant is active or inactive. """
    # p.registered is a boolean, it is only present when there is no device id attached to the
    # participant, which only occurs if the participant has never registered, of if someone clicked
    # the clear device id button on the participant page.
    if not registered:
        return "Not Registered"
    
    # get a list of all the tracking timestamps
    all_the_times = [
        some_timestamp for some_timestamp in (
            last_upload,
            last_get_latest_surveys,
            last_set_password,
            last_set_fcm_token,
            last_get_latest_device_settings,
            last_register_user,
        ) if some_timestamp
    ]
    now = timezone.now()
    # each of the following sections will only be visible if the participant has done something
    # MORE RECENT than the time specified.
    # The values need to be alphanumerically ordered, so that sorting works on the webpage
    five_minutes_ago = now - timedelta(minutes=5)
    if any(t > five_minutes_ago for t in all_the_times):
        return "Active (just now)"
    
    one_hour_ago = now - timedelta(hours=1)
    if any(t > one_hour_ago for t in all_the_times):
        return "Active (last hour)"
    
    one_day_ago = now - timedelta(days=1)
    if any(t > one_day_ago for t in all_the_times):
        return "Active (past day)"
    
    one_week_ago = now - timedelta(days=7)
    if any(t > one_week_ago for t in all_the_times):
        return "Active (past week)"
    
    return "Inactive"


def get_interventions_and_fields(query: ParticipantQuerySet) -> Dict[int, Dict[str, Union[str, datetime]]]:
    """ intervention dates and fields have a many-to-one relationship with participants, which means
    we need to do it as a single query (or else deal with some very gross autofilled code that I'm
    not sure populates None values in a way that we desire), from which we create a lookup dict to
    then find them later. """
    # we need the fields and intervention values, organized per-participant, by name.
    interventions_lookup = defaultdict(dict)
    fields_lookup = defaultdict(dict)
    query = query.values_list(
        "id", "intervention_dates__intervention__name", "intervention_dates__date",
        "field_values__field__field_name", "field_values__value"
    )
    
    # can you have an intervention date and a field date of the same name? probably.
    for p_id, int_name, int_date, field_name, field_value in query:
        interventions_lookup[p_id][int_name] = int_date
        fields_lookup[p_id][field_name] = field_value
    
    return dict(fields_lookup), dict(interventions_lookup)
