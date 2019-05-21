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
    )


@dashboard_api.route("/dashboard/<string:study_id>/<string:patient_id>", methods=["GET"])
@authenticate_admin_study_access
def query_data_for_user(study_id, patient_id):
    try:
        participant = Participant.objects.filter(study=study_id, patient_id=patient_id).get()
    except Participant.DoesNotExist:
        return abort(400, "No such user exists.")

    start, end = extract_date_args()
    data_stream = extract_data_stream_args()

    args = {"participant__id": participant.id}

    if start:
        args["time_bin__gte "] = start,
    if end:
        args["time_bin__lte "] = end,
    if data_stream:
        args["data_type"] = data_stream

    chunks = ChunkRegistry.objects.filter(**args).values_list("file_size", "data_type", "time_bin")

    ret_chunks = []
    for chunk in chunks:
        ret_chunks.append({
            "bytes": chunk[0],
            "data_stream": chunk[1],
            "time_bin": chunk[2].strftime(REDUCED_API_TIME_FORMAT),
        })

    return Response(
        dumps(ret_chunks),
        mimetype="text/json",
    )


def extract_date_args():
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


def extract_data_stream_args():
    data_stream = request.values.get("data_stream", None)
    if data_stream:
        if data_stream not in ALL_DATA_STREAMS:
            return abort(400, "unrecognized data stream '%s'" % data_stream)

    return data_stream
