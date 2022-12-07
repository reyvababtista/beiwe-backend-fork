from collections import Counter
from datetime import datetime, timedelta, tzinfo
from pprint import pprint
from time import sleep

from dateutil.tz import gettz
from django.utils.timezone import localtime

from constants.common_constants import DEV_TIME_FORMAT
from constants.message_strings import MESSAGE_SEND_SUCCESS
from database.data_access_models import FileToProcess
from database.profiling_models import UploadTracking
from database.schedule_models import ArchivedEvent, ScheduledEvent
from database.study_models import Study
from database.survey_models import Survey
from database.user_models_participant import Participant
from database.user_models_researcher import Researcher
from libs.utils.dev_utils import disambiguate_participant_survey, TxtClr


# Some utility functions for a quality of life.


def as_local(dt: datetime, tz=gettz("America/New_York")):
    return localtime(dt, tz)


def PARTICIPANT(patient_id: str or int):
    if isinstance(patient_id, int):
        return Participant.objects.get(pk=patient_id)
    return Participant.objects.get(patient_id=patient_id)

P = PARTICIPANT  # Pah, who has time for that.


def RESEARCHER(username: str or int):
    if isinstance(username, int):
        return Researcher.objects.get(pk=username)
    try:
        return Researcher.objects.get(username=username)
    except Researcher.DoesNotExist:
        return Researcher.objects.get(username__icontains=username)


R = RESEARCHER


def SURVEY(id_or_name: str or int):
    if isinstance(id_or_name, int):
        return Survey.objects.get(pk=id_or_name)
    try:
        return Survey.objects.get(object_id=id_or_name)
    except Survey.DoesNotExist:
        return Survey.objects.get(name__icontains=id_or_name)


def STUDY(id_or_name: str or int):
    if isinstance(id_or_name, int):
        return Study.objects.get(pk=id_or_name)
    try:
        return Study.objects.get(object_id=id_or_name)
    except Study.DoesNotExist:
        return Study.objects.get(name__icontains=id_or_name)


def count():
    return FileToProcess.objects.count()


def status():
    pprint(
        sorted(Counter(FileToProcess.objects.values_list("participant__patient_id", flat=True))
               .most_common(), key=lambda x: x[1])
    )


def watch_processing():
    # cannot be imported on EB servers
    from libs.celery_control import (CeleryNotRunningException, get_processing_active_job_ids,
        get_processing_reserved_job_ids, get_processing_scheduled_job_ids)
    
    periodicity = 5
    orig_start = localtime()
    a_now = orig_start
    s_now = orig_start
    r_now = orig_start
    active = []
    scheduled = []
    registered = []
    prior_users = 0
    
    for i in range(2**64):
        errors = 0
        start = localtime()
        
        count = FileToProcess.objects.count()
        user_count = FileToProcess.objects.values_list("participant__patient_id",
                                                       flat=True).distinct().count()
        
        if prior_users != user_count:
            print(f"{start:} Number of participants with files to process: {user_count}")
        
        print(f"{start}: {count} files to process")
        
        try:
            a_now, active = localtime(), get_processing_active_job_ids()
        except CeleryNotRunningException:
            errors += 1
        try:
            s_now, scheduled = localtime(), get_processing_scheduled_job_ids()
        except CeleryNotRunningException:
            errors += 1
        try:
            r_now, registered = localtime(), get_processing_reserved_job_ids()
        except CeleryNotRunningException:
            errors += 1
        
        if errors:
            print(f"  (Couldn't connect to celery on {errors} attempt(s), data is slightly stale.)")
        
        print(a_now, "active tasks:", active)
        print(s_now, "scheduled tasks:", scheduled)
        print(r_now, "registered tasks:", registered)
        
        prior_users = user_count
        
        # we will set a minimum time between info updates, database call can be slow.
        end = localtime()
        total = abs((start - end).total_seconds())
        wait = periodicity - total if periodicity - total > 0 else 0
        
        print("\n=================================\n")
        sleep(wait)


def watch_uploads():
    while True:
        start = localtime()
        data = list(UploadTracking.objects.filter(
            timestamp__gte=(start - timedelta(minutes=1))).values_list("file_size", flat=True))
        end = localtime()
        total = abs((start - end).total_seconds())
        
        # we will set a minimum time between prints at 2 seconds, database call can be slow.
        wait = 2 - total if 0 < (2 - total) < 2 else 0
        
        print("time delta: %ss, %s files, %.4fMB in the past minute" % (
            total + wait, len(data), (sum(data) / 1024.0 / 1024.0)))
        sleep(wait)


def get_and_summarize(patient_id: str):
    p = Participant.objects.get(patient_id=patient_id)
    byte_sum = sum(UploadTracking.objects.filter(participant=p).values_list("file_size", flat=True))
    print(f"Total Data Uploaded: {byte_sum/1024/1024}MB")
    
    counter = Counter(
        path.split("/")[2] for path in
        FileToProcess.objects.filter(participant=p).values_list("s3_file_path", flat=True)
    )
    return counter.most_common()


@disambiguate_participant_survey
def find_notification_events(
        participant: Participant = None,
        survey: Survey or str = None,
        schedule_type: str = None,
        tz: tzinfo = gettz('America/New_York'),
        flat=False
    ):
    """ THIS FUNCTION IS FOR DEBUGGING PURPOSES ONLY

    Throw in a participant and or survey object, OR THEIR IDENTIFYING STRING and we make it work

    'survey_type'  will filter by survey type, duh.
    'flat'         disables alternating line colors.
    'tz'           will normalize timestamps to that timezone, default is us east.
    """
    filters = {}
    if participant:
        filters['participant'] = participant
    if schedule_type:
        filters["schedule_type"] = schedule_type
    if survey:
        filters["survey_archive__survey"] = survey
    elif participant:  # if no survey, yes participant:
        filters["survey_archive__survey__in"] = participant.study.surveys.all()
    
    # order by participant to separate out the core related events, then order by survey
    # to group the participant's related events together, and do this in order of most recent
    # at the top of all sub-lists.
    query = ArchivedEvent.objects.filter(**filters).order_by(
        "participant__patient_id", "survey_archive__survey__object_id", "-created_on")
    
    print(f"There were {query.count()} sent scheduled events matching your query.")
    participant_name = ""
    survey_id = ""
    for a in query:
        # only print participant name and survey id when it changes
        if a.participant.patient_id != participant_name:
            print(f"\nparticipant {TxtClr.CYAN}{a.participant.patient_id}{TxtClr.BLACK}:")
            participant_name = a.participant.patient_id
        if a.survey.object_id != survey_id:
            print(f"{a.survey.survey_type} {TxtClr.CYAN}{a.survey.object_id}{TxtClr.BLACK}:")
            survey_id = a.survey.object_id
        
        # data points of interest for sending information
        sched_time = localtime(a.scheduled_time, tz)
        sent_time = localtime(a.created_on, tz)
        time_diff_minutes = (sent_time - sched_time).total_seconds() / 60
        sched_time_print = datetime.strftime(sched_time, DEV_TIME_FORMAT)
        sent_time_print = datetime.strftime(sent_time, DEV_TIME_FORMAT)
        
        print(
            f"  {a.schedule_type} FOR {TxtClr.GREEN}{sched_time_print}{TxtClr.BLACK} "
            f"SENT {TxtClr.GREEN}{sent_time_print}{TxtClr.BLACK}  "
            f"\u0394 of {time_diff_minutes:.1f} min",
            end="",
            # \u0394 is the delta character
        )
        
        if a.status == MESSAGE_SEND_SUCCESS:
            print(f'  status: "{TxtClr.GREEN}{a.status}{TxtClr.BLACK}"')
        else:
            print(f'  status: "{TxtClr.YELLOW}{a.status}{TxtClr.BLACK}"')
        
        if not flat:
            # these lines get hard to read, color helps, we can alternate brightness like this!
            TxtClr.brightness_swap()


@disambiguate_participant_survey
def find_pending_events(
        participant: Participant = None, survey: Survey or str = None,
        tz: tzinfo = gettz('America/New_York'),
):
    """ THIS FUNCTION IS FOR DEBUGGING PURPOSES ONLY

    Throw in a participant and or survey object, OR THEIR IDENTIFYING STRING and we make it work
    'tz' will normalize timestamps to that timezone, default is us east.
    """
    # this is a simplified, modified version ofg the find_notification_events on ArchivedEvent.
    filters = {}
    if participant:
        filters['participant'] = participant
    if survey:
        filters["survey"] = survey
    elif participant:  # if no survey, yes participant:
        filters["survey__in"] = participant.study.surveys.all()
    
    query = ScheduledEvent.objects.filter(**filters).order_by(
        "survey__object_id", "participant__patient_id", "-scheduled_time", "-created_on"
    )
    survey_id = ""
    for a in query:
        # only print participant name and survey id when it changes
        if a.survey.object_id != survey_id:
            print(f"{a.survey.survey_type} {TxtClr.CYAN}{a.survey.object_id}{TxtClr.BLACK}:")
            survey_id = a.survey.object_id
        
        # data points of interest for sending information
        sched_time = localtime(a.scheduled_time, tz)
        sched_time_print = datetime.strftime(sched_time, DEV_TIME_FORMAT)
        print(
            f"  {a.get_schedule_type()} FOR {TxtClr.CYAN}{a.participant.patient_id}{TxtClr.BLACK}"
            f" AT {TxtClr.GREEN}{sched_time_print}{TxtClr.BLACK}",
        )
