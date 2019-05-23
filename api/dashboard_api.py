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

#I think this should be able to be referenced since this exact thing is in the constants.py
#but they are undefined unless this is included
ACCELEROMETER = "accelerometer"
BLUETOOTH = "bluetooth"
CALL_LOG = "calls"
GPS = "gps"
IDENTIFIERS = "identifiers"
ANDROID_LOG_FILE = "app_log"
IOS_LOG_FILE = "ios_log"
POWER_STATE = "power_state"
SURVEY_ANSWERS = "survey_answers"
SURVEY_TIMINGS = "survey_timings"
TEXTS_LOG = "texts"
VOICE_RECORDING = "audio_recordings"
IMAGE_FILE = "image_survey"
WIFI = "wifi"
PROXIMITY = "proximity"
GYRO = "gyro"
MAGNETOMETER = "magnetometer"
DEVICEMOTION = "devicemotion"
REACHABILITY = "reachability"

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

@dashboard_api.route("/dashboard/<string:study_id>/<string:patient_id>/<string:data_stream>", methods=["GET", "POST"])
@authenticate_admin_study_access
def query_data_for_user_for_data_stream(study_id, patient_id, data_stream):
    participant = get_participant(patient_id, study_id)
    start, end = extract_date_args_from_request()
    data = dashboard_chunkregistry_query(participant.id, data_stream=data_stream, start=start, end=end)
    return Response(dumps(data), mimetype="text/json")



#for dashboard of a singular patient
@dashboard_api.route("/dashboard/<string:study_id>/patient/<string:patient_id>", methods=["GET"])
@authenticate_admin_study_access
def query_data_for_user(study_id, patient_id):
    participant = get_participant(patient_id, study_id)
    start, end = extract_date_args_from_request()
    data_stream = extract_data_stream_args_from_request()
    chunks = dashboard_chunkregistry_query(participant.id, data_stream=data_stream, start=start, end=end)

    # create dictionary of all data streams to numbers - feels silly but enumerate doesn't work?
    stream_nums = {
        ACCELEROMETER: 0,
        BLUETOOTH: 1,
        CALL_LOG: 2,
        DEVICEMOTION: 3,
        GPS: 4,
        IDENTIFIERS: 5,
        GYRO: 6,
        ANDROID_LOG_FILE: 7,
        MAGNETOMETER: 8,
        POWER_STATE: 9,
        REACHABILITY: 10,
        SURVEY_ANSWERS: 11,
        SURVEY_TIMINGS: 12,
        TEXTS_LOG: 13,
        VOICE_RECORDING: 14,
        WIFI: 15,
        PROXIMITY: 16,
        IOS_LOG_FILE: 17,
        IMAGE_FILE: 18,
    }

    #create list of unique time
    if len(chunks) != 0:
        times = []
        iterator = 0
        copy = False
        for item in chunks:
            curr_time = item["time_bin"].strftime(REDUCED_API_TIME_FORMAT)
            for prev in range(iterator):
                prev_item = chunks[prev]
                prev_time = prev_item["time_bin"].strftime(REDUCED_API_TIME_FORMAT)
                if curr_time == prev_time:
                    copy = True
            if copy == False:
                times.append(curr_time)
            copy = False
            iterator+=1

        byte_streams = []

        #create list of lists for each stream and bytes in those streams at a specific time
        for stream in ALL_DATA_STREAMS:
            s = []
            s.append(stream)
            byte_streams.append(s)
        for time in times:
            populated = [0] * len(ALL_DATA_STREAMS)
            for item in chunks:
                if item["time_bin"].strftime(REDUCED_API_TIME_FORMAT) == time:
                    stream = item["data_stream"]
                    populated[int(stream_nums.get(stream))] = 1
                    byte_streams[int(stream_nums.get(stream))].append(item["bytes"])
            for i in range(len(populated)): #to make sure that blanks are entered if no data
                if populated[i] == 0:
                    byte_streams[i].append(-1)
    else: #edge case if no data has been entered
        byte_streams = []
        times = []

    return render_template(
        'dashboard/participant_dash.html',
        participant=participant,
        times=times,
        byte_streams=byte_streams,
    )



def dashboard_chunkregistry_query(participant_id, data_stream=None, start=None, end=None):
    """ Queries ChunkRegistry based on the provided parameters and returns a list of dictionaries
    with 3 keys: bytes, data_stream, and time_bin. """

    args = {"participant__id": participant_id}
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

    return chunks


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

