from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, tzinfo
from pprint import pprint
from time import sleep
from typing import Dict, List, Tuple, Union

from dateutil.tz import gettz
from django.utils import timezone
from django.utils.timezone import localtime

from constants.action_log_messages import HEARTBEAT_PUSH_NOTIFICATION_SENT
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


def heartbeat_summary(p: Participant, max_age: int = 12):
    # Get the heartbeat timestamps and push notification events, print out all the timestamps in
    # day-by-day and hour-by-hour sections print statements, and print time deltas since the
    # previous received heartbeat event.
    max_age = (timezone.now() - timedelta(hours=max_age)).replace(minute=0, second=0, microsecond=0)
    
    # queries
    heartbeats_query = p.heartbeats.order_by("timestamp") \
        .filter(timestamp__gte=max_age) \
        .values_list("timestamp", "message")
    heartbeat_notifications = p.action_logs.order_by("timestamp") \
        .filter(action=HEARTBEAT_PUSH_NOTIFICATION_SENT, timestamp__gte=max_age) \
        .values_list("timestamp", flat=True)
    
    # insert events, add a timedelta of difference with the previous event.
    events: List[Tuple[datetime, Union[timedelta, str]]] = []
    for i, (t, message) in enumerate(heartbeats_query):
        events.append((
            as_local(t),
            timedelta(seconds=0) if i == 0 else t - events[i-1][0],  # force first a delta to 0.
            message
        ))
    
    # add the push notification events, second object in the tuple as a string, then re-sort.
    for t in heartbeat_notifications:
        events.append((as_local(t), "heartbeat notification sent.", ""))
    events.sort(key=lambda x: x[0])
    
    # group into days
    events_by_day = defaultdict(list)
    for t, delta_or_message, message in events:
       events_by_day[t.date()].append((t, delta_or_message, message))
    
    # got type signature?
    events_by_day: Dict[date, List[Tuple[datetime, Union[timedelta, str]]]] = dict(events_by_day)
    
    # initialize previous day to the first day
    prev_day = events[0][0].strftime('%Y-%m-%d')
    for day, day_data in events_by_day.items():
        
        # print the day header if it's a new day
        if day.strftime('%Y-%m-%d') != prev_day:
            prev_day = day.strftime('%Y-%m-%d')
            print(f"\n[{prev_day}]")
        
        for hour in range(24):
            # filter out events that are not in this hour
            one_hours_data = [(hb, delta_or_message, message) for (hb, delta_or_message, message) in day_data if hb.hour == hour]
            if not one_hours_data:
                continue
            
            # print the hour header if there are events in that hour
            print(f"  {hour:02}:00 - {hour:02}:59")
            
            # print each event in that hour, timedeltas are printed in seconds and minutes. 
            for t, delta_or_message, message in one_hours_data:
                if isinstance(delta_or_message, timedelta):
                    s = delta_or_message.total_seconds()
                    print(f"    {t.strftime('%H:%M:%S')} (Δ {s:.1f} sec, {s/60:.1f} min), - {message}")
                else:
                    print(f"    {t.strftime('%H:%M:%S')} - {delta_or_message}")
            print()
    
    final_timestamp = events[-1][0]
    print(
        f"and it has been {(timezone.now() - final_timestamp).total_seconds() / 60:.1f} "
        "minutes since that last event."
    )
