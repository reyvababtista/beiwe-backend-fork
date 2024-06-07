import csv
import json
from io import StringIO

from django.contrib import messages
from django.db.models import ProtectedError
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from authentication.admin_authentication import authenticate_researcher_study_access
from database.schedule_models import Intervention, InterventionDate
from database.study_models import Study, StudyField
from database.user_models_participant import Participant, ParticipantFieldValue
from libs.internal_types import ResearcherRequest
from libs.intervention_utils import (correct_bad_interventions, intervention_survey_data,
    survey_history_export)
from libs.participant_table_api import (common_data_extraction_for_apis, filtered_participants,
    get_table_columns, get_values_for_participants_table)


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
    table_data = common_data_extraction_for_apis(study)
    
    # we need to write the data to a buffer, and then return the buffer as a response
    buffer = StringIO()
    writer = csv.writer(buffer, dialect="excel")
    writer.writerow(get_table_columns(study))  # write the header row
    writer.writerows(table_data)
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








    
