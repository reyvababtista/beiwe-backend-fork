import csv
import json
import shutil
import traceback
from datetime import date, datetime, timedelta
from multiprocessing.pool import ThreadPool
from os import makedirs
from os.path import dirname, exists as file_exists, join as path_join
from time import sleep
from typing import Dict, Tuple

from dateutil.tz import UTC
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from pkg_resources import get_distribution

from constants.celery_constants import FOREST_QUEUE
from constants.data_access_api_constants import CHUNK_FIELDS
from constants.forest_constants import (CLEANUP_ERROR as CLN_ERR, ForestFiles, ForestTaskStatus,
    ForestTree, NO_DATA_ERROR, ROOT_FOREST_TASK_PATH, TREE_COLUMN_NAMES_TO_SUMMARY_STATISTICS,
    YEAR_MONTH_DAY)
from database.data_access_models import ChunkRegistry
from database.tableau_api_models import ForestTask, SummaryStatisticDaily
from database.user_models_participant import Participant
from libs.celery_control import forest_celery_app, safe_apply_async
from libs.copy_study import format_study
from libs.internal_types import ChunkRegistryQuerySet
from libs.intervention_utils import intervention_survey_data
from libs.s3 import s3_retrieve
from libs.sentry import make_error_sentry, SentryTypes
from libs.streaming_zip import determine_file_name
from libs.utils.date_utils import get_timezone_shortcode

from forest.jasmine.traj2stats import gps_stats_main
from forest.sycamore.base import get_submits_for_tableau
from forest.willow.log_stats import log_stats_main


"""
This entire code path could be rewritten as a class, but all the data we need or want to track is
collected on the ForestTask object.  For code organization reasons the [overwhelming] majority of
code for running any given forest task should be in this file, not attached to the ForestTask
database model. Deducing file paths, most dealing with constants and other simple lookups, including
parameters for each tree, should be placed on that class.
"""


MIN_TIME = datetime.min.time()
MAX_TIME = datetime.max.time()


class NoSentryException(Exception): pass
class BadForestField(Exception): pass

# don't stick in constants, we want forest imports limited to forest related files, forest is not
# installed on frontend servers, forest constants must remain freely importable.
TREE_TO_FOREST_FUNCTION = {
    ForestTree.jasmine: gps_stats_main,
    ForestTree.willow: log_stats_main,
    ForestTree.sycamore: get_submits_for_tableau,
}

DEBUG_CELERY_FOREST = False


def log(*args, **kwargs):
    if DEBUG_CELERY_FOREST:
        print("celery_forest debug: ", end="")
        print(*args, **kwargs)


#
## Celery and dev helpers
#
def enqueue_forest_task(**kwargs):
    safe_apply_async(
        celery_run_forest,
        expires=(datetime.utcnow() + timedelta(minutes=5)).replace(second=30, microsecond=0, tzinfo=UTC),
        max_retries=0,
        retry=False,
        task_publish_retry=False,
        task_track_started=True,
        **kwargs
    )


def create_forest_celery_tasks():
    """ Basic entrypoint, does what it says """
    pending_tasks = ForestTask.objects.filter(status=ForestTaskStatus.queued)
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        for task in pending_tasks:
            # always print
            print(
                f"Queueing up celery task for {task.participant} on tree {task.forest_tree} "
                f"from {task.data_date_start} to {task.data_date_end}"
            )
            enqueue_forest_task(args=[task.id])


#
## The forest task runtime
#
@forest_celery_app.task(queue=FOREST_QUEUE)
def celery_run_forest(forest_task_id):
    with transaction.atomic():
        task: ForestTask = ForestTask.objects.filter(id=forest_task_id).first()
        participant: Participant = task.participant
        
        # Check if there already is a running task for this participant and tree, handling
        # concurrency and requeuing of the ask if necessary (locks db rows until end of transaction)
        tasks = ForestTask.objects.select_for_update() \
                .filter(participant=participant, forest_tree=task.forest_tree)
        
        # if any other forest tasks are running, exit.
        if tasks.filter(status=ForestTaskStatus.running).exists():
            return
        
        # Get the chronologically earliest task that's queued
        task: ForestTask = tasks.filter(status=ForestTaskStatus.queued) \
                .order_by("-data_date_start").first()
        
        if task is None:  # Should be unreachable...
            return
        
        task.update_only(  # Set metadata on the task to running
            status=ForestTaskStatus.running,
            process_start_time=timezone.now(),
            forest_version=get_distribution("forest").version
        )
    
    # ChunkRegistry time_bin hourly chunks are in UTC, and only have hourly datapoints for all
    # automated data, but manually entered data is more specific with minutes, seconds, etc.  We
    # want our query for source data to use the study's timezone such that starts of days align to
    # local midnight and end-of-day to 11:59.59pm. Weird fractional timezones will be noninclusive
    # of their first hour of data between midnight and midnight + 1 hour, except for manually
    # entered data streams which will instead align to the calendar date in the study timezone. Any
    # such "missing" fraction of an hour is instead included at the end of the previous day.
    starttime_midnight = datetime.combine(task.data_date_start, MIN_TIME, task.participant.study.timezone)
    endtime_11_59pm = datetime.combine(task.data_date_end, MAX_TIME, task.participant.study.timezone)
    log("starttime_midnight: ", starttime_midnight.isoformat())
    log("endtime_11_59pm: ", endtime_11_59pm.isoformat())
    
    # do the thing
    run_forest_task(task, starttime_midnight, endtime_11_59pm)


def run_forest_task(task: ForestTask, start: datetime, end: datetime):
    """ Given a time range, downloads all data and executes a tree on that data. """
    try:
        download_data(task, start, end)
        run_forest(task)
        upload_cached_files(task)
        task.update_only(status=ForestTaskStatus.success)
    except BaseException as e:
        task.update_only(status=ForestTaskStatus.error, stacktrace=traceback.format_exc())
        log("task.stacktrace 1:", task.stacktrace)
        tags = {k: str(v) for k, v in task.as_dict().items()}  # report with many tags
        if not isinstance(e, NoSentryException):
            with make_error_sentry(SentryTypes.data_processing, tags=tags):
                raise
    finally:
        # This is entirely boilerplate for reporting cleanup operations cleanly to both sentry and
        # forest task infrastructure.
        try:
            log("deleting files 1")
            clean_up_files(task)
        except Exception:
            # mergeing stack traces, handling null case, then conditionally report with tags
            task.update_only(stacktrace=((task.stacktrace or "") + CLN_ERR + traceback.format_exc()))
            log("task.stacktrace 2:", task.stacktrace)
            tags = {k: str(v) for k, v in task.as_dict().items()}
            with make_error_sentry(SentryTypes.data_processing, tags=tags):
                raise
    
    log("task.status:", task.status)
    log("deleting files 2")
    clean_up_files(task)  # if this fails you probably have server oversubscription issues.
    task.update_only(process_end_time=timezone.now())


def run_forest(forest_task: ForestTask):
    # Run Forest
    params_dict = forest_task.get_params_dict()
    log("params_dict:", params_dict)
    forest_task.update_only(params_dict_cache=json.dumps(params_dict))
    
    log("running:", forest_task.forest_tree)
    TREE_TO_FOREST_FUNCTION[forest_task.forest_tree](**params_dict)
    log("done running:", forest_task.forest_tree)
    
    # Save data
    forest_task.update_only(forest_output_exists=construct_summary_statistics(forest_task))


def download_data(forest_task: ForestTask, start: datetime, end: datetime):
    chunks = ChunkRegistry.objects.filter(
        participant=forest_task.participant,
        time_bin__gte=start,
        time_bin__lte=end,
        data_type__in=ForestFiles.lookup(forest_task.forest_tree)
    )
    file_size = chunks.aggregate(Sum('file_size')).get('file_size__sum')
    if file_size is None:
        raise NoSentryException(NO_DATA_ERROR)
    forest_task.update_only(total_file_size=file_size)
    
    # Download data
    download_data_files(forest_task, chunks)
    forest_task.update_only(process_download_end_time=timezone.now())
    log("task.process_download_end_time:", forest_task.process_download_end_time.isoformat())
    
    # get extra custom files for any trees that need them (currently just sycamore)
    if forest_task.forest_tree == ForestTree.sycamore:
        get_interventions_data(forest_task)
        get_study_config_data(forest_task)


def construct_summary_statistics(task: ForestTask):
    """ Construct summary statistics from forest output, returning whether or not any
        SummaryStatisticDaily has potentially been created or updated. """
    
    if not file_exists(task.forest_results_path):
        log("path does not exist:", task.forest_results_path)
        return False
    
    log("tree:", task.taskname)
    with open(task.forest_results_path, "r") as f:
        reader = csv.DictReader(f)
        has_data = False
        log("opened file...")
        
        for line in reader:
            has_data = True
            summary_date = date(
                int(float(line['year'])),
                int(float(line['month'])),
                int(float(line['day'])),
            )
            # if timestamp is outside of desired range, skip.
            if not (task.data_date_start < summary_date < task.data_date_end):
                continue
            
            updates = {
                task.taskname: task,
                "timezone": get_timezone_shortcode(summary_date, task.participant.study.timezone),
            }
            for column_name, value in line.items():
                if column_name in TREE_COLUMN_NAMES_TO_SUMMARY_STATISTICS:
                    # look up column translation, coerce empty strings to Nones
                    summary_stat_field = TREE_COLUMN_NAMES_TO_SUMMARY_STATISTICS[column_name]
                    # force Nones on no data fields, not empty strings (db table issue)
                    updates[summary_stat_field] = value if value != '' else None
                elif column_name in YEAR_MONTH_DAY:
                    continue
                else:
                    raise BadForestField(column_name)
            
            data = {"date": summary_date, "defaults": updates, "participant": task.participant}
            log("creating SummaryStatisticDaily:", data)
            SummaryStatisticDaily.objects.update_or_create(**data)
    
    return has_data


#
## Files
#
def clean_up_files(forest_task: ForestTask):
    """ Delete temporary input and output files from this Forest run. """
    for i in range(10):
        try:
            shutil.rmtree(forest_task.root_path_for_task)
        except OSError:  # this is pretty expansive, but there are an endless number of os errors...
            pass
        # file system can be slightly slow, we need to sleep. (this code never executes on frontend)
        sleep(0.5)
        if not file_exists(forest_task.root_path_for_task):
            return
    raise Exception(
        f"Could not delete folder {forest_task.root_path_for_task} for participant {forest_task.external_id}, tried {i} times."
    )


def download_data_files(task: ForestTask, chunks: ChunkRegistryQuerySet) -> None:
    """ Download only the files needed for the forest task. """
    ensure_folders_exist(task)
    # this is an iterable, this is intentional, retain it.
    params = (
        (task, chunk) for chunk in chunks.values("study__object_id", *CHUNK_FIELDS)
    )
    # and run!
    with ThreadPool(4) as pool:
        for _ in pool.imap_unordered(func=batch_create_file, iterable=params):
            pass


def batch_create_file(task_and_chunk_tuple: Tuple[ForestTask, Dict]):
    """ Wrapper for basic file download operations so that it can be run in a ThreadPool. """
    # weird unpack of variables, do s3_retrieve.
    forest_task, chunk = task_and_chunk_tuple
    contents = s3_retrieve(chunk["chunk_path"], chunk["study__object_id"], raw_path=True)
    # file ops, sometimes we have to add folder structure (surveys)
    file_name = path_join(forest_task.data_input_path, determine_file_name(chunk))
    makedirs(dirname(file_name), exist_ok=True)
    with open(file_name, "xb") as f:
        f.write(contents)


def get_interventions_data(forest_task: ForestTask):
    """ Generates a study interventions file for the participant's survey and returns the path to it """
    ensure_folders_exist(forest_task)
    with open(forest_task.interventions_filepath, "w") as f:
        f.write(json.dumps(intervention_survey_data(forest_task.participant.study)))


def get_study_config_data(forest_task: ForestTask):
    """ Generates a study config file for the participant's survey and returns the path to it. """
    ensure_folders_exist(forest_task)
    with open(forest_task.study_config_path, "w") as f:
        f.write(format_study(forest_task.participant.study))


def ensure_folders_exist(forest_task: ForestTask):
    """ This io is minimal, simply always make sure these folder structures exist. """
    makedirs(ROOT_FOREST_TASK_PATH, exist_ok=True)
    makedirs(forest_task.root_path_for_task, exist_ok=True)
    # files
    makedirs(dirname(forest_task.interventions_filepath), exist_ok=True)
    makedirs(dirname(forest_task.study_config_path), exist_ok=True)
    # folders
    makedirs(forest_task.data_input_path, exist_ok=True)
    makedirs(forest_task.data_output_path, exist_ok=True)
    makedirs(forest_task.data_base_path, exist_ok=True)


# Extras
def upload_cached_files(forest_task: ForestTask):
    """ Find output files from forest tasks and consume them. """
    if file_exists(forest_task.all_bv_set_path):
        with open(forest_task.all_bv_set_path, "rb") as f:
            forest_task.save_all_bv_set_bytes(f.read())
    if file_exists(forest_task.all_memory_dict_path):
        with open(forest_task.all_memory_dict_path, "rb") as f:
            forest_task.save_all_memory_dict_bytes(f.read())
