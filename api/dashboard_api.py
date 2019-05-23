from __future__ import print_function

from datetime import datetime
from json import dumps

from flask import abort, Blueprint, render_template, request, Response

from config.constants import ALL_DATA_STREAMS, REDUCED_API_TIME_FORMAT
from database.data_access_models import ChunkRegistry
from database.study_models import Study
from database.user_models import Participant
from libs.admin_authentication import authenticate_admin_study_access

dashboard_api = Blueprint('dashboard_api', __name__)

DATETIME_FORMAT_ERROR = \
    "Dates and times provided to this endpoint must be formatted like this: 2010-11-22T4 (%s)" % REDUCED_API_TIME_FORMAT

@dashboard_api.route("/dashboard/<string:study_id>", methods=["GET"])
@authenticate_admin_study_access
def dashboard_page(study_id=None):
    # participants needs to be json serializable, need to dump queryset into a list.
    participants = list(Participant.objects.filter(study=study_id).values_list("patient_id", flat=True))
    return render_template(
        'dashboard/dashboard.html',
        study_name=Study.objects.filter(pk=study_id).values_list("name", flat=True).get(),
        participants=participants,
        study_id=study_id,
    )


#for dashboard of a singular patient
@dashboard_api.route("/dashboard/<string:study_id>/patient/<string:patient_id>", methods=["GET"])
@authenticate_admin_study_access
def query_data_for_user(study_id, patient_id):
    participant = get_participant(patient_id, study_id)
    start, end = extract_date_args_from_request()
    data_stream = extract_data_stream_args_from_request()
    data = dashboard_chunkregistry_query(participant.id, data_stream=data_stream, start=start, end=end)
    return Response(dumps(data), mimetype="text/json")


@dashboard_api.route("/dashboard/<string:study_id>/<string:patient_id>/<string:data_stream>", methods=["GET", "POST"])
@authenticate_admin_study_access
def query_data_for_user_for_data_stream(study_id, patient_id, data_stream):
    participant = get_participant(patient_id, study_id)
    start, end = extract_date_args_from_request()
    data = dashboard_chunkregistry_query(participant.id, data_stream=data_stream, start=start, end=end)
    return Response(dumps(data), mimetype="text/json")


def dashboard_chunkregistry_query(participant_id, data_stream=None, start=None, end=None):
    """ Queries ChunkRegistry based on the provided parameters and returns a list of dictionaries
    with 3 keys: bytes, data_stream, and time_bin. """

    args = {"participant__id": participant_id}
    participant = Participant.objects.get(id=participant_id)
    if start:
        args["time_bin__gte "] = start,
    if end:
        args["time_bin__lte "] = end,
    if data_stream:
        args["data_type"] = data_stream

    # on a (good) test device running on sqlite, for 12,200 chunks, this takes ~135ms
    # sticking the query_set directly into a list is a slight speedup. (We need it all in memory anyway.)
    chunks = list(
        ChunkRegistry.objects.filter(**args)
        .extra(
            select={
                # rename the data_type and file_size fields in the db query itself for speed
                'data_stream': 'data_type',
                'bytes': 'file_size',
            }
        ).values("bytes", "data_stream", "time_bin")
    )

    # on a (good) test device running on sqlite, for 12,200 chunks, this takes ~18ms

    #the times list (no repeats)

    if len(chunks) != 0:
        times = []
        iterator = 0
        copy = False
        for item in chunks:
            curr_time = item[2].strftime(REDUCED_API_TIME_FORMAT)
            for prev in range(iterator):
                prev_item = chunks[prev]
                prev_time = prev_item[2].strftime(REDUCED_API_TIME_FORMAT)
                if(curr_time == prev_time):
                    copy = True
            if copy == False:
                times.append(curr_time)
            copy = False
            iterator+=1

        #List of Data Streams which each hold a list of bytes per time
        #1. iterate over the diff types of data streams
        #2. iterate over the possible times (collapsed from repeated possible times)
        #3. iterate over the items and if they have the correct data stream and time, enter the bytes to curr_data list
        #4. append the curr_data list to the byte_streams list to have a list of lists

        byte_streams = []
        for stream in ALL_DATA_STREAMS:
            curr_data = []
            curr_data.append(stream)
            for time in times:
                found = False
                for item in chunks:
                    if item[1].lower() == stream.lower() and item[2].strftime(REDUCED_API_TIME_FORMAT) == time:
                        curr_data.append(item[0])
                        found = True
                        break
                if found == False:
                    curr_data.append(-1)
            byte_streams.append(curr_data)

    else:
        byte_streams = []
        times = []

    return render_template(
        'dashboard/participant_dash.html',
        participant=participant,
        times=times,
        byte_streams=byte_streams,
    )


    # byte_streams = []
    # for stream in ALL_DATA_STREAMS:
    #     s = []
    #     s.append(stream)
    #     byte_streams.append(s)
    #
    # for time in times:
    #     populated = [ 0 * ALL_DATA_STREAMS]
    #     for item in chunks:
    #         if item[2].strftime(REDUCED_API_TIME_FORMAT) == time:
    #             it = 0
    #             for stream in ALL_DATA_STREAMS:
    #                 if item[1].lower() == stream.lower():
    #                     populated[it] = 1
    #                     byte_streams[it].append(item[0])
    #                     break
    #                 it+=1
    #     for i in populated:
    #         if i == 0:
    #             byte_streams[i].append(-1)


def extract_date_args_from_request():
    """ Gets start and end arguments from GET/POST params, throws 400 on date formatting errors. """
    start = request.values.get("start", None)
    end = request.values.get("end", None)
    try:
        if start:
            start = datetime.strptime(start, REDUCED_API_TIME_FORMAT)
        if end:
            end = datetime.strptime(end, REDUCED_API_TIME_FORMAT)
    except ValueError as e:
        return abort(400, DATETIME_FORMAT_ERROR)

    return start, end


def extract_data_stream_args_from_request():
    """ Gets data stream if it is provided as a request POST or GET parameter,
    throws 400 errors on unknown data streams. """
    data_stream = request.values.get("data_stream", None)
    if data_stream:
        if data_stream not in ALL_DATA_STREAMS:
            return abort(400, "unrecognized data stream '%s'" % data_stream)
    return data_stream


def get_participant(patient_id, study_id):
    """ Just factoring out a common abort operation. """
    try:
        return Participant.objects.get(study=study_id, patient_id=patient_id)
    except Participant.DoesNotExist:
        # 2 useful error messages
        if not Participant.objects.get(patient_id=patient_id).exists():
            return abort(400, "No such user exists.")
        else:
            return abort(400, "No such user exists in this study.")

