import json
from datetime import datetime, timedelta

from celery import Celery
from kombu.exceptions import OperationalError

from config.constants import (CELERY_CONFIG_LOCATION, DATA_PROCESSING_CELERY_SERVICE,
    PUSH_NOTIFICATION_SEND_SERVICE)


class CeleryNotRunningException(Exception): pass


def get_celery_app(service_name: str):
    # the location of the celery configuration file is in the folder above the project folder.
    try:
        with open(CELERY_CONFIG_LOCATION, 'r') as f:
            manager_info = f.read()
    except IOError:
        print("No celery configuration present...")
        return None

    manager_ip, password = manager_info.splitlines()

    # note that the 2nd trailing slash here is actually required and
    pyamqp_endpoint = f'pyamqp://beiwe:{password}@{manager_ip}//'

    # set up the celery app...
    return Celery(
        service_name,
        broker=pyamqp_endpoint,
        backend='rpc://',
        task_publish_retry=False,
        task_track_started=True,
    )


# if None then there is no celery app.
processing_celery_app = get_celery_app(DATA_PROCESSING_CELERY_SERVICE)
push_send_celery_app = get_celery_app(PUSH_NOTIFICATION_SEND_SERVICE)


def inspect():
    """ Inspect is annoyingly unreliable and has a default 1 second timeout. """
    # this import appears to need to come after the celery app is loaded, class is dynamic.

    if processing_celery_app is None or push_send_celery_app is None:
        raise CeleryNotRunningException()

    from celery.task.control import inspect as celery_inspect
    now = datetime.now()
    fail_time = now + timedelta(seconds=20)

    while now < fail_time:
        try:
            return celery_inspect(timeout=0.1)
        except CeleryNotRunningException:
            now = datetime.now()
            continue

    raise CeleryNotRunningException()


def safe_apply_async(task_func: callable, *args, **kwargs):
    for i in range(10):
        try:
            return task_func.apply_async(*args, **kwargs)
        except OperationalError:
            # Enqueuing can fail deep inside amqp/transport.py with an OperationalError. We
            # wrap it in some retry logic when this occurs.
            # Dec. 2019 - this code was written in early 2017, it has never failed.
            if i < 3:
                pass
            else:
                raise


def get_revoked_job_ids():
    return inspect().revoked().values()


# Notifications...
def get_notification_scheduled_job_ids():
    """ Returns list of ids (can be empty), or None if celery isn't currently running. """
    return _get_job_ids(inspect().scheduled(), "notifications")


def get_notification_reserved_job_ids():
    """ Returns list of ids (can be empty), or None if celery isn't currently running. """
    return _get_job_ids(inspect().reserved(), "notifications")


def get_notification_active_job_ids():
    """ Returns list of ids (can be empty), or None if celery isn't currently running. """
    return _get_job_ids(inspect().active(), "notifications")


# Processing
def get_processing_scheduled_job_ids():
    """ Returns list of ids (can be empty), or None if celery isn't currently running. """
    return _get_job_ids(inspect().scheduled(), "processing")


def get_processing_reserved_job_ids():
    """ Returns list of ids (can be empty), or None if celery isn't currently running. """
    return _get_job_ids(inspect().reserved(), "processing")


def get_processing_active_job_ids():
    """ Returns list of ids (can be empty), or None if celery isn't currently running. """
    return _get_job_ids(inspect().active(), "processing")


def _get_job_ids(celery_query_dict, celery_app_suffix):
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
        raise CeleryNotRunningException()

    # below could be substantially improved. itertools chain....
    all_processing_jobs = []
    for worker_name, list_of_jobs in celery_query_dict.items():
        if worker_name.endswith(celery_app_suffix):
            all_processing_jobs.extend(list_of_jobs)

    all_args = []
    for job_arg in [job['args'] for job in all_processing_jobs]:
        args = json.loads(job_arg)
        # safety/sanity check, assert that there is only 1 integer id in a list and that it is a list.
        assert isinstance(args, list)
        assert len(args) == 1
        assert isinstance(args[0], int)
        all_args.append(args[0])

    return all_args
