import json
from time import sleep

from celery import Celery
from django.core.exceptions import ImproperlyConfigured
from kombu.exceptions import OperationalError


class CeleryNotRunningException(Exception): pass

DATA_PROCESSING_CELERY_SERVICE = "services.celery_data_processing"
PUSH_NOTIFICATION_MANAGE_SERVICE = "services.push_notification_manage"
PUSH_NOTIFICATION_SEND_SERVICE = "services.push_notification_send"

def get_celery_app(service_name: str):
    try:
        with open("/home/ubuntu/manager_ip", 'r') as f:
            manager_info = f.read()
    except IOError:
        raise ImproperlyConfigured("No celery configuration present")

    manager_ip, password = manager_info.splitlines()

    # note that the 2nd trailing slash here is actually required and
    pyamqp_endpoint = f'pyamqp://beiwe:{password}@{manager_ip}//'

    return Celery(
        service_name,
        broker=pyamqp_endpoint,
        backend='rpc://',
        task_publish_retry=False,
        task_track_started=True
    )

    # try:
    #     celery_app = Celery(
    #             "services.celery_data_processing",
    #             # note that the 2nd trailing slash here is actually required and
    #             broker=
    #             backend='rpc://',
    #             task_publish_retry=False,
    #             task_track_started=True
    #     )
    #     print("connected to celery with discovered credentials.")
    # except IOError:
    #     celery_app = Celery(
    #             "services.celery_data_processing",
    #             broker='pyamqp://guest@127.0.0.1//',
    #             backend='rpc://',
    #             task_publish_retry=False,
    #             task_track_started=True
    #     )
    #     print("connected to celery without credentials.")


processing_celery_app = get_celery_app(DATA_PROCESSING_CELERY_SERVICE)
# push_manage_celery_app = get_celery_app(PUSH_NOTIFICATION_MANAGE_SERVICE)
push_send_celery_app = get_celery_app(PUSH_NOTIFICATION_SEND_SERVICE)


# this import appears to need to come after the celery app is loaded
from celery.task.control import inspect  # this import appears to need to come after the celery app is loaded


def celery_try_20_times(func, *args, **kwargs):
    """ single purpose helper, for some reason celery can fail to ... exist? unclear."""
    for i in range(1, 21):
        try:
            return func(*args, **kwargs)
        except CeleryNotRunningException as e:
            print(f"encountered error running {func.__name__}, retrying")
            sleep(0.5)
            if i > 19:
                raise


def safe_apply_async(task_func: callable, *args, **kwargs):
    """"""
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
        raise CeleryNotRunningException()

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
