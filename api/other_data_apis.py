import json

import orjson
from django.db.models.functions import Substr
from django.http import FileResponse, StreamingHttpResponse
from django.http.response import HttpResponse
from django.views.decorators.http import require_POST

from authentication.data_access_authentication import (api_credential_check,
    api_study_credential_check)
from database.user_models_participant import Participant
from database.user_models_researcher import StudyRelation
from libs.internal_types import ApiResearcherRequest, ApiStudyResearcherRequest
from libs.intervention_utils import intervention_survey_data, survey_history_export
from libs.utils.effiicient_paginator import EfficientQueryPaginator


@require_POST
@api_credential_check
def get_studies(request: ApiResearcherRequest):
    """
    Retrieve a dict containing the object ID and name of all Study objects that the user can access
    If a GET request, access_key and secret_key must be provided in the URL as GET params. If
    a POST request (strongly preferred!), access_key and secret_key must be in the POST
    request body.
    :return: string: JSON-dumped dict {object_id: name}
    """
    return HttpResponse(
        json.dumps(
            dict(StudyRelation.objects.filter(
                researcher=request.api_researcher).values_list("study__object_id", "study__name")
            )
        )
    )


@require_POST
@api_study_credential_check()
def get_users_in_study(request: ApiStudyResearcherRequest):
    # json can't operate on queryset, need as list.
    return HttpResponse(
        json.dumps(list(request.api_study.participants.values_list('patient_id', flat=True)))
    )


@require_POST
@api_study_credential_check()
def download_study_interventions(request: ApiStudyResearcherRequest):
    return HttpResponse(json.dumps(intervention_survey_data(request.api_study)))


@require_POST
@api_study_credential_check()
def download_study_survey_history(request: ApiStudyResearcherRequest):
    study = request.api_study
    fr = FileResponse(
        survey_history_export(study).decode(),  # okay, whatever, it needs to be a string, not bytes
        content_type="text/json",
        as_attachment=True,
        filename=f"{study.object_id}_surveys_history_data.json",
    )
    fr.set_headers(None)  # django is still stupid?
    return fr


@require_POST
@api_credential_check
def get_participant_upload_history(request: ApiStudyResearcherRequest):
    participant_id = request.POST.get('participant_id')
    omit_keys = check_request_for_omit_keys_param(request)
    
    # EXTREMELY OBSCURE DETAIL: the annotated pseudofield "field_name" is forced to come after real
    # fields in the key ordering on query.values _but not on query.values_list_???
    FIELDS_TO_SERIALIZE = ["file_size", "timestamp", "file_name"]
    
    if not participant_id:
        return HttpResponse(content=b"", status=400)
    # raising a 404 on participant not found is not an information leak.
    # get_object_or_404 renders the 404 page, which is not what we want.
    try:
        participant = Participant.objects.get(patient_id=participant_id)
    except Participant.DoesNotExist:
        return HttpResponse(content=b"", status=404)
    
    # authentication is weird because this endpoint doesn't have the mandatory study so code
    # patterns might change.
    # if the researcher is not a site admin, they must have a relationship to the study.
    if not request.api_researcher.site_admin:
        if not StudyRelation.determine_relationship_exists(
            study_pk=participant.study.pk, researcher_pk=request.api_researcher.pk
        ):
            return HttpResponse(content=b"", status=403)
    
    # We want to reduce the amount of raw data, so we strip out some unnecessary details both in
    # the query and using orjson options.
    # the file path string contains the patient id, let's remove it and the slash afterwords.
    # Substr(expression, pos, length=None, **extra) - pos is 1-indexed, length  of none means to the end.
    
    query = participant.upload_trackers.order_by("timestamp")
    start = len(participant.patient_id) + 2
    query = query.annotate(file_name=Substr("file_path", start, length=None))
    
    # we use our efficient paginator class to stream the bytes of the database query.
    paginator = EfficientQueryPaginator(
        filtered_query=query, 
        page_size=10000,
        values=FIELDS_TO_SERIALIZE if not omit_keys else None,
        values_list=FIELDS_TO_SERIALIZE if omit_keys else None,
    )
    
    # OPT_OMIT_MICROSECONDS - obvious
    # OPT_UTC_Z - UTC timezone serialized to Z instead of +00:00
    options = orjson.OPT_OMIT_MICROSECONDS | orjson.OPT_UTC_Z
    return StreamingHttpResponse(
        paginator.stream_orjson_paginate(option=options), content_type="application/json"
    )


def check_request_for_omit_keys_param(request):
    """ Returns true if the request has a POST param omit_keys set to "true". """
    omit_keys = request.POST.get("omit_keys", "false")
    return omit_keys == "true"
