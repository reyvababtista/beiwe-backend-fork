from typing import Dict, List

from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from authentication.admin_authentication import authenticate_researcher_study_access
from constants.data_stream_constants import COMPLETE_DATA_STREAM_DICT, DASHBOARD_DATA_STREAMS
from database.study_models import Study
from database.user_models_participant import Participant
from libs.endpoint_helpers.dashboard_helpers import (create_next_past_urls,
    dashboard_chunkregistry_date_query, dashboard_chunkregistry_query,
    extract_date_args_from_request, get_bytes_data_stream_match, get_unique_dates, handle_filters,
    parse_data_streams)
from libs.internal_types import ResearcherRequest
from pages.admin_pages import conditionally_display_study_status_warnings


#
## Dashboard Endpoints
#
@require_http_methods(["GET", "POST"])
@authenticate_researcher_study_access
def dashboard_page(request: ResearcherRequest, study_id: int):
    """ information for the general dashboard view for a study """
    study = get_object_or_404(Study, pk=study_id)
    participants = list(Participant.objects.filter(study=study_id).values_list("patient_id", flat=True))
    conditionally_display_study_status_warnings(request, study)
    return render(
        request,
        'dashboard/dashboard.html',
        context=dict(
            study=study,
            participants=participants,
            study_id=study_id,
            data_stream_dict=COMPLETE_DATA_STREAM_DICT,
            page_location='dashboard_landing',
        )
    )


@require_http_methods(["GET", "POST"])
@authenticate_researcher_study_access
def get_data_for_dashboard_datastream_display(
    request: ResearcherRequest, study_id: int, data_stream: str
):
    """ Parses information for the data stream dashboard view GET and POST requests left the post
    and get requests in the same function because the body of the get request relies on the
    variables set in the post request if a post request is sent --thus if a post request is sent
    we don't want all of the get request running. """
    study = Study.objects.get(pk=study_id)  # already checked in decorator
    
    # general data fetching
    participants = Participant.objects.filter(study=study).order_by("patient_id")
    data_exists, first_day, last_day, unique_dates, byte_streams = parse_data_streams(
        request, study, data_stream, participants
    )
    if first_day is None or not data_exists:
        next_url = past_url = ""
    else:
        start, end = extract_date_args_from_request(request, study.timezone)
        next_url, past_url = create_next_past_urls(first_day, last_day, start=start, end=end)
    
    show_color, color_low_range, color_high_range, all_flags_list = handle_filters(
        request, study, data_stream
    )
    
    return render(
        request,
        'dashboard/data_stream_dashboard.html',
        context=dict(
            study=study,
            data_stream=COMPLETE_DATA_STREAM_DICT.get(data_stream),
            times=unique_dates,
            byte_streams=byte_streams,
            base_next_url=next_url,
            base_past_url=past_url,
            study_id=study_id,
            data_stream_dict=COMPLETE_DATA_STREAM_DICT,
            color_low_range=color_low_range,
            color_high_range=color_high_range,
            first_day=first_day,
            last_day=last_day,
            show_color=show_color,
            all_flags_list=all_flags_list,
            page_location='dashboard_data',
        )
    )

@require_http_methods(["GET", "POST"])
@authenticate_researcher_study_access
def dashboard_participant_page(request: ResearcherRequest, study_id, patient_id):
    """ Parses data to be displayed for the singular participant dashboard view """
    study = get_object_or_404(Study, pk=study_id)
    participant = get_object_or_404(Participant, patient_id=patient_id, study_id=study_id)
    
    # query is optimized for bulk participants, so this is a little weird
    chunk_data = dashboard_chunkregistry_query(participant)
    chunks = chunk_data[participant.patient_id] if participant.patient_id in chunk_data else {}
    
    # ----------------- dates for bytes data streams -----------------------
    if chunks:
        start, end = extract_date_args_from_request(request, study.timezone)
        first_day, last_day = dashboard_chunkregistry_date_query(study, participant=participant)
        unique_dates, first_date_data_entry, last_date_data_entry = get_unique_dates(
            start, end, first_day, last_day, chunks
        )
        next_url, past_url = create_next_past_urls(
            first_date_data_entry, last_date_data_entry, start=start, end=end
        )
        byte_streams: Dict[str, List[int]] = {
            stream: [get_bytes_data_stream_match(chunks, date, stream) for date in unique_dates]
                for stream in DASHBOARD_DATA_STREAMS
        }
    else:
        last_date_data_entry = first_date_data_entry = None
        byte_streams = {}
        unique_dates = []
        next_url = past_url = first_date_data_entry = last_date_data_entry = ""
    
    patient_ids = list(
        Participant.objects.filter(study=study_id)
            .exclude(patient_id=patient_id).values_list("patient_id", flat=True)
    )
    return render(
        request,
        'dashboard/participant_dashboard.html',
        context=dict(
            study=study,
            patient_id=patient_id,
            participant=participant,
            times=unique_dates,
            byte_streams=byte_streams,
            next_url=next_url,
            past_url=past_url,
            patient_ids=patient_ids,
            study_id=study_id,
            first_date_data=first_date_data_entry,
            last_date_data=last_date_data_entry,
            data_stream_dict=COMPLETE_DATA_STREAM_DICT,
            page_location='dashboard_patient',
        )
    )
