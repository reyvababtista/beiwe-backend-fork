import csv
import pickle
from collections import defaultdict
from datetime import date, datetime, timedelta

import orjson
from django.contrib import messages
from django.http.response import FileResponse, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from authentication.admin_authentication import (authenticate_admin,
    authenticate_researcher_study_access, forest_enabled)
from constants.celery_constants import ForestTaskStatus
from constants.common_constants import DEV_TIME_FORMAT, EARLIEST_POSSIBLE_DATA_DATE
from constants.data_access_api_constants import CHUNK_FIELDS
from constants.forest_constants import (FOREST_TASKVIEW_PICKLING_EMPTY,
    FOREST_TASKVIEW_PICKLING_ERROR, FOREST_TREE_REQUIRED_DATA_STREAMS, ForestTree)
from database.data_access_models import ChunkRegistry
from database.forest_models import ForestTask, SummaryStatisticDaily
from database.study_models import Study
from database.system_models import ForestVersion
from database.user_models_participant import Participant
from forms.django_forms import CreateTasksForm
from libs.forest_utils import download_output_file
from libs.http_utils import easy_url
from libs.internal_types import ParticipantQuerySet, ResearcherRequest
from libs.streaming_zip import ZipGenerator
from libs.utils.date_utils import daterange
from serializers.forest_serializers import display_true, ForestTaskCsvSerializer


TASK_SERIALIZER_FIELDS = [
    # raw
    "data_date_end",
    "data_date_start",
    "forest_output_exists",
    "id",
    "stacktrace",
    "status",
    "total_file_size",
    # to be popped
    "external_id",  # -> uuid in the urls
    "participant__patient_id",  # -> patient_id
    "pickled_parameters",
    "forest_tree",  # -> forest_tree_display as .title()
    "output_zip_s3_path", # need to identify that it is present at all
    # datetimes
    "process_end_time",  # -> dev time format
    "process_start_time",  # -> dev time format
    "process_download_end_time",  # -> dev time format
    "created_on",  # -> dev time format
]

@require_GET
@authenticate_researcher_study_access
@forest_enabled
def forest_tasks_progress(request: ResearcherRequest, study_id=None):
    study: Study = Study.objects.get(pk=study_id)
    participants: ParticipantQuerySet = Participant.objects.filter(study=study_id)
    
    # generate chart of study analysis progress logs
    tasks = ForestTask.objects.filter(participant__in=participants).order_by("created_on")
    
    start_date = (study.get_earliest_data_time_bin() or study.created_on).date()
    end_date = (study.get_latest_data_time_bin() or timezone.now()).date()
    
    params = {}
    results = defaultdict(lambda: "--")
    # this code simultaneously builds up the chart of most recent forest results for date ranges
    # by participant and tree, and tracks the metadata
    for task in tasks:
        for a_date in daterange(task.data_date_start, task.data_date_end, inclusive=True):
            results[(task.participant_id, task.forest_tree, a_date)] = task
            params[(task.participant_id, task.forest_tree, a_date)] = task.safe_unpickle_parameters_as_string()
    
    # generate the date range for charting
    dates = list(daterange(start_date, end_date, inclusive=True))
    
    chart = []
    for participant in participants:
        for tree in ForestTree.values():
            row = [participant.patient_id, tree] + \
                [results[(participant.id, tree, date)] for date in dates]
            chart.append(row)
    
    # ensure that within each tree, only a single set of param values are used (only the most recent runs
    # are considered, and unsuccessful runs are assumed to invalidate old runs, clearing params)
    params_conflict = False
    for tree in {k[1] for k in params.keys()}:
        if len({m for k, m in params.items() if m is not None and k[1] == tree}) > 1:
            params_conflict = True
            break
    
    return render(
        request,
        'forest/forest_tasks_progress.html',  # has been renamed internally because this is imprecise.
        context=dict(
            study=study,
            chart_columns=["participant", "tree"] + dates,
            status_choices=ForestTaskStatus,
            params_conflict=params_conflict,
            start_date=start_date,
            end_date=end_date,
            chart=chart  # this uses the jinja safe filter and should never involve user input
        )
    )


@require_http_methods(['GET', 'POST'])
@authenticate_admin
@forest_enabled
def create_tasks(request: ResearcherRequest, study_id=None):
    # Only a SITE admin can queue forest tasks
    if not request.session_researcher.site_admin:
        return HttpResponse(content="", status=403)
    try:
        study = Study.objects.get(pk=study_id)
    except Study.DoesNotExist:
        return HttpResponse(content="", status=404)
    
    # FIXME: remove this double endpoint pattern, it is bad.
    if request.method == "GET":
        return render_create_tasks(request, study)
    form = CreateTasksForm(data=request.POST, study=study)
    
    if not form.is_valid():
        error_messages = [
            f'"{field}": {message}'
            for field, messages in form.errors.items()
            for message in messages
        ]
        error_messages_string = "\n".join(error_messages)
        messages.warning(request, f"Errors:\n\n{error_messages_string}")
        return render_create_tasks(request, study)
    
    form.save()
    messages.success(request, "Forest tasks successfully queued!")
    return redirect(easy_url("forest_pages.task_log", study_id=study_id))


@require_GET
@authenticate_researcher_study_access
@forest_enabled
def task_log(request: ResearcherRequest, study_id=None):
    query = ForestTask.objects.filter(participant__study_id=study_id)\
        .order_by("-created_on").values(*TASK_SERIALIZER_FIELDS)
    tasks = []
    
    for task_dict in query:
        extern_id = task_dict.pop("external_id")
        # renames (could be optimized in the query, but speedup is negligible)
        task_dict["patient_id"] = task_dict.pop("participant__patient_id")
        
        # rename and transform
        task_dict["forest_tree_display"] = task_dict.pop("forest_tree").title()
        task_dict["created_on_display"] = task_dict.pop("created_on").strftime(DEV_TIME_FORMAT)
        task_dict["forest_output_exists_display"] = display_true(task_dict["forest_output_exists"])
        # dates/times that require safety
        task_dict["process_end_time"] = task_dict["process_end_time"].strftime(DEV_TIME_FORMAT) \
             if task_dict["process_end_time"] else None
        task_dict["process_start_time"] = task_dict["process_start_time"].strftime(DEV_TIME_FORMAT) \
             if task_dict["process_start_time"] else None
        task_dict["process_download_end_time"] = task_dict["process_download_end_time"].strftime(DEV_TIME_FORMAT) \
             if task_dict["process_download_end_time"] else None
        # urls
        task_dict["cancel_url"] = easy_url(
            "forest_pages.cancel_task", study_id=study_id, forest_task_external_id=extern_id,
        )
        task_dict["has_output_data"] = task_dict["forest_output_exists"]
        task_dict["download_url"] = easy_url(
            "forest_pages.download_task_data", study_id=study_id, forest_task_external_id=extern_id,
        )
        
        # raw output data data is only available if the task has completed successfully, and not
        # on older tasks that were run before we started saving the output data.
        if task_dict.pop("output_zip_s3_path"):
            task_dict["has_output_downloadable_data"] = True
            task_dict["download_output_url"] = easy_url(
                "forest_pages.download_output_data", study_id=study_id, forest_task_external_id=extern_id,
            )
        
        # the pickled parameters have some error cases.
        if task_dict["pickled_parameters"]:
            try:
                task_dict["params_dict"] = repr(pickle.loads(task_dict.pop("pickled_parameters")))
            except Exception:
                task_dict["params_dict"] = FOREST_TASKVIEW_PICKLING_ERROR
        else:
            task_dict["params_dict"] = FOREST_TASKVIEW_PICKLING_EMPTY
        tasks.append(task_dict)
    
    return render(
        request,
        "forest/task_log.html",
        context=dict(
            study=Study.objects.get(pk=study_id),
            status_choices=ForestTaskStatus,
            forest_log=orjson.dumps(tasks).decode(),  # orjson is very fast and handles the remaining date objects
        )
    )


@require_GET
@authenticate_admin
def download_task_log(request: ResearcherRequest):
    forest_tasks = ForestTask.objects.order_by("created_on")
    return FileResponse(
        stream_forest_task_log_csv(forest_tasks),
        content_type="text/csv",
        filename=f"forest_task_log_{timezone.now().isoformat()}.csv",
        as_attachment=True,
    )


@require_POST
@authenticate_admin
@forest_enabled
def cancel_task(request: ResearcherRequest, study_id, forest_task_external_id):
    if not request.session_researcher.site_admin:
        return HttpResponse(content="", status=403)
    
    number_updated = \
        ForestTask.objects.filter(
            external_id=forest_task_external_id, status=ForestTaskStatus.queued
        ).update(
            status=ForestTaskStatus.cancelled,
            stacktrace=f"Canceled by {request.session_researcher.username} on {date.today()}",
        )
    
    if number_updated > 0:
        messages.success(request, "Forest task successfully cancelled.")
    else:
        messages.warning(request, "Sorry, we were unable to find or cancel this Forest task.")
    
    return redirect(easy_url("forest_pages.task_log", study_id=study_id))


@require_GET
@authenticate_admin
@forest_enabled
def download_task_data(request: ResearcherRequest, study_id, forest_task_external_id):
    
    try:
        forest_task: ForestTask = ForestTask.objects.get(
            external_id=forest_task_external_id, participant__study_id=study_id
        )
    except ForestTask.DoesNotExist:
        return HttpResponse(content="", status=404)
    
    # this time manipulation is copied right out of the celery forest task runner.
    starttime_midnight = datetime.combine(
        forest_task.data_date_start, datetime.min.time(), forest_task.participant.study.timezone
    )
    endtime_11_59pm = datetime.combine(
        forest_task.data_date_end, datetime.max.time(), forest_task.participant.study.timezone
    )
    
    chunks: str = ChunkRegistry.objects.filter(
        participant=forest_task.participant,
        time_bin__gte=starttime_midnight,
        time_bin__lt=endtime_11_59pm,  # inclusive
        data_type__in=FOREST_TREE_REQUIRED_DATA_STREAMS[forest_task.forest_tree]
    ).values(*CHUNK_FIELDS)
    
    filename = "_".join([
            forest_task.participant.patient_id,
            forest_task.forest_tree,
            str(forest_task.data_date_start),
            str(forest_task.data_date_end),
            "data",
        ]) + ".zip"
    
    f = FileResponse(
        ZipGenerator(chunks, False),
        content_type="zip",
        as_attachment=True,
        filename=filename,
    )
    f.set_headers(None)  # this is just a thing you have to do, its a django bug.
    return f


@require_GET
@authenticate_admin
@forest_enabled
def download_output_data(request: ResearcherRequest, study_id, forest_task_external_id):
    try:
        forest_task: ForestTask = ForestTask.objects.get(
            external_id=forest_task_external_id, participant__study_id=study_id
        )
    except ForestTask.DoesNotExist:
        return HttpResponse(content="", status=404)
    
    filename = "_".join([
            forest_task.participant.patient_id,
            forest_task.forest_tree,
            str(forest_task.data_date_start),
            str(forest_task.data_date_end),
            "output",
            forest_task.created_on.strftime(DEV_TIME_FORMAT),
        ]) + ".zip"
    
    # for some reason FileResponse doesn't work when handed a bytes object, so we are forcing the
    # headers for attachment and filename in a custom HttpResponse. Baffling. I guess FileResponse
    # is really only for file-like objects.
    return HttpResponse(
        download_output_file(forest_task),
        content_type="zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def render_create_tasks(request: ResearcherRequest, study: Study):
    # this is the fastest way to get earliest and latest dates, even for large numbers of matches.
    # SummaryStatisticDaily is orders of magnitude smaller than ChunkRegistry.
    dates = list(
        SummaryStatisticDaily.objects
        .exclude(date__lte=max(EARLIEST_POSSIBLE_DATA_DATE, study.created_on.date()))
        .filter(participant__in=study.participants.all())
        .order_by("date")
        .values_list("date", flat=True)
    )
    start_date = dates[0] if dates else study.created_on.date()
    end_date = dates[-1] if dates else timezone.now().date()
    forest_info = ForestVersion.get_singleton_instance()
    
    # start_date = dates[0] if dates and dates[0] >= EARLIEST_POSSIBLE_DATA_DATE else study.created_on.date()
    # end_date = dates[-1] if dates and dates[-1] <= timezone.now().date() else timezone.now().date()
    return render(
        request,
        "forest/create_tasks.html",
        context=dict(
            study=study,
            participants=list(
                study.participants.order_by("patient_id").values_list("patient_id", flat=True)
            ),
            trees=ForestTree.choices(),
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            forest_version=forest_info.package_version.title(),
            forest_commit=forest_info.git_commit,
        )
    )


def stream_forest_task_log_csv(forest_tasks):
    buffer = CSVBuffer()
    writer = csv.DictWriter(buffer, fieldnames=ForestTaskCsvSerializer.Meta.fields)
    writer.writeheader()
    yield buffer.read()
    
    for forest_task in forest_tasks:
        writer.writerow(ForestTaskCsvSerializer(forest_task).data)
        yield buffer.read()


class CSVBuffer:
    line = ""
    
    def read(self):
        return self.line
    
    def write(self, line):
        self.line = line
