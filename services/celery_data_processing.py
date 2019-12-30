from os.path import abspath
from sys import path

# add the root of the project into the path to allow cd-ing into this folder and running the script.
path.insert(0, abspath(__file__).rsplit('/', 2)[0])

# Load Django
from config import load_django

from kombu.exceptions import OperationalError
from celery import Celery, states

STARTED_OR_WAITING = [states.PENDING, states.RECEIVED, states.STARTED]
FAILED = [states.REVOKED, states.RETRY, states.FAILURE]

try:
    with open("/home/ubuntu/manager_ip", 'r') as f:
        manager_info = f.read()
    manager_ip, password = manager_info.splitlines()
    celery_app = Celery(
            "data_processing_tasks",
            # note that the 2nd trailing slash here is actually required and
            broker='pyamqp://beiwe:%s@%s//' % (password, manager_ip),
            backend='rpc://',
            task_publish_retry=False,
            task_track_started=True
    )
    print("connected to celery with discovered credentials.")
except IOError:
    celery_app = Celery(
            "data_processing_tasks",
            broker='pyamqp://guest@127.0.0.1//',
            backend='rpc://',
            task_publish_retry=False,
            task_track_started=True
    )
    print("connected to celery without credentials.")

from celery.task.control import inspect  # this import appears to need to come after the celery app is loaded

################################################################################
############################# Data Processing ##################################
################################################################################
import json

from datetime import datetime, timedelta

from config.constants import FILE_PROCESS_PAGE_SIZE
from database.user_models import Participant
from libs.file_processing import do_process_user_file_chunks
from libs.sentry import make_error_sentry


def safe_queue_user(*args, **kwargs):
    """
    Queue the given user's file processing with the given keyword arguments. This should
    return immediately and leave the processing to be done in the background via celery.
    In case there is an error with enqueuing the process, retry it several times until
    it works.
    """
    for i in range(10):
        try:
            return queue_user.apply_async(*args, **kwargs)
        except OperationalError:
            # Enqueuing can fail deep inside amqp/transport.py with an OperationalError. We
            # wrap it in some retry logic when this occurs.
            # Dec. 2019 - this code was written in early 2017, it has never failed.
            if i < 3:
                pass
            else:
                raise


def create_file_processing_tasks():
    """ Generates tasks to enqueue.  This is called every 6 minutes, and tasks have a lifetime
    of 6 minutes.  Note that tasks are not removed from the queue by RabbitMQ, but by Celery.
    inspecting the queue will continue to display the tasks that have not been sent to Celery
    until the most recent job is finished.

    Also, for some reason 5 minutes is the smallest value that .... works.  At all.
    No clue why.
    """
    expiry = datetime.now() + timedelta(minutes=5)

    with make_error_sentry('data'):
        participant_set = set(
            Participant.objects.filter(files_to_process__isnull=False)
                .distinct()
                # .order_by("id")  # For debugging, forces overlap conflicts.
                .order_by("?")     # don't want a single user blocking everyone because they are at the front.
                .values_list("id", flat=True)
        )
        active_set = set(get_active_job_ids())
        participants_to_process = participant_set - active_set
        print("Queueing these participants:", ",".join(participants_to_process))

        for participant_id in participants_to_process:
            # Queue all users' file processing, and generate a list of currently running jobs
            # to use to detect when all jobs are finished running.
            safe_queue_user(
                args=[participant_id],
                max_retries=0,
                expires=expiry,
                task_track_started=True,
                task_publish_retry=False,
                retry=False
            )
        print(f"{len(participants_to_process)} users queued for processing")


def celery_process_file_chunks(participant_id):
    """ This is the function is queued up, it runs through all new uploads from a specific user and
    'chunks' them. Handles logic for skipping bad files, raising errors. """
    time_start = datetime.now()
    participant = Participant.objects.get(id=participant_id)

    number_bad_files = 0
    tags = {'user_id': participant.patient_id}
    error_sentry = make_error_sentry('data', tags=tags)
    print("processing files for %s" % participant.patient_id)

    while True:
        previous_number_bad_files = number_bad_files
        starting_length = participant.files_to_process.exclude(deleted=True).count()
        
        print("%s processing %s, %s files remaining" % (datetime.now(), participant.patient_id, starting_length))
        number_bad_files += do_process_user_file_chunks(
                count=FILE_PROCESS_PAGE_SIZE,
                error_handler=error_sentry,
                skip_count=number_bad_files,
                participant=participant,
        )
        # If no files were processed, quit processing
        if participant.files_to_process.exclude(deleted=True).count() == starting_length:
            if previous_number_bad_files == number_bad_files:
                # 2 Cases:
                #   1) every file broke, blow up. (would cause infinite loop otherwise).
                #   2) no new files.
                break
            else:
                continue

        # put maximum time limit per user
        if (time_start - datetime.now()).total_seconds() > 60*60*3:
                break

@celery_app.task
def queue_user(participant):
    return celery_process_file_chunks(participant)
queue_user.max_retries = 0  # may not be necessary


# Useful for debugging, we use get_active_job_ids to ensure that there are no multiple concurrent
# file processing operations for a single user

def get_revoked_job_ids():
    return inspect().revoked().values()


def get_scheduled_job_ids():
    """ Returns list of ids (can be empty), or None if celery isn't currently running. """
    return _get_job_ids(inspect().scheduled())


def get_reserved_job_ids():
    """ Returns list of ids (can be empty), or None if celery isn't currently running. """
    return _get_job_ids(inspect().reserved())


def get_active_job_ids():
    """ Returns list of ids (can be empty), or None if celery isn't currently running. """
    return _get_job_ids(inspect().active())


def _get_job_ids(celery_query_dict):
    """ Data structure looks like this, we just want that args component.
        Returns list of ids (can be empty), or None if celery isn't currently running.
    {'celery@ip-172-31-78-176': [{'id': '12e579ee-c603-4f06-b80c-dd78c330e539',
       'name': 'services.celery_data_processing.queue_user',
       'args': '[7235]',
       'kwargs': '{}',
       'type': 'services.celery_data_processing.queue_user',
       'hostname': 'celery@ip-172-31-78-176',
       'time_start': 2387953.778238536,
       'acknowledged': True,
       'delivery_info': {'exchange': '',
        'routing_key': 'celery',
        'priority': 0,
        'redelivered': False},
       'worker_pid': 27291},
        {'id': 'd49aad01-2392-4607-91f7-5f9416a9941f',
         'name': 'services.celery_data_processing.queue_user',
         'args': '[7501]',
         'kwargs': '{}',
         'type': 'services.celery_data_processing.queue_user',
         'hostname': 'celery@ip-172-31-78-176',
         'time_start': 2387939.015288787,
         'acknowledged': True,
         'delivery_info': {'exchange': '',
          'routing_key': 'celery',
          'priority': 0,
          'redelivered': False},
         'worker_pid': 27292}]}
    """

    # for when celery isn't running
    if celery_query_dict is None:
        return None

    # below could be substantially improved. itertools chain....
    all_jobs = []
    for list_of_jobs in celery_query_dict.values():
        all_jobs.extend(list_of_jobs)

    all_args = []
    for job_arg in [job['args'] for job in all_jobs]:
        args = json.loads(job_arg)
        # safety/sanity check, assert that there is only 1 integer id in a list and that it is a list.
        assert isinstance(args, list)
        assert len(args) == 1
        assert isinstance(args[0], int)
        all_args.append(args[0])

    return all_args


# for debugging.  running this file will enqueue users
if __name__ == "__main__":
    create_file_processing_tasks()
