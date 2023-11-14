import itertools
from typing import List, Tuple

from django.utils import timezone

from constants.common_constants import CHUNKS_FOLDER, PROBLEM_UPLOADS
from database.user_models_participant import Participant, ParticipantDeletionEvent
from libs.s3 import s3_delete_many_versioned, s3_list_files, s3_list_versions
from libs.security import generate_easy_alphanumeric_string


DELETION_PAGE_SIZE = 250


def add_particpiant_for_deletion(participant: Participant):
    """ adds a participant to the deletion queue. """
    try:
        ParticipantDeletionEvent.objects.get(participant=participant)
        return
    except ParticipantDeletionEvent.DoesNotExist:
        pass
    ParticipantDeletionEvent.objects.create(participant=participant)


def run_next_queued_participant_data_deletion():
    """ checks ParticipantDeletionEvent for un-run events, runs deletion over all of them. """
    # only deletion events that have not been confirmed completed (purge_confirmed_time) and only
    # events that have last_updated times more than 30 minutes ago. (The deletion process constantly
    # updates the database with a count of files deleted as it runs.)
    deletion_event = ParticipantDeletionEvent.objects.filter(
        purge_confirmed_time__isnull=True,
        last_updated__lt=timezone.now() - timezone.timedelta(minutes=30),
    ).first()
    if not deletion_event:
        return
    
    deletion_event.save()  # mark the event as processing...
    
    # mark the participant as retired (field name is unregistered, its a legacy name), disable
    # easy enrollment, set a random password (validation runs on save so it needs to be valid)
    deletion_event.participant.update(
        unregistered=True, easy_enrollment=False, device_id="", os_type=""
    )
    deletion_event.participant.set_password(generate_easy_alphanumeric_string(50))
    
    delete_participant_data(deletion_event)
    # MAKE SURE TO UPDATE TESTS IF YOU ADD MORE RELATIONS TO THIS LIST
    deletion_event.participant.chunk_registries.all().delete()
    deletion_event.participant.summarystatisticdaily_set.all().delete()
    deletion_event.participant.lineencryptionerror_set.all().delete()
    deletion_event.participant.iosdecryptionkey_set.all().delete()
    deletion_event.participant.foresttask_set.all().delete()
    deletion_event.participant.encryptionerrormetadata_set.all().delete()
    deletion_event.participant.files_to_process.all().delete()
    deletion_event.participant.pushnotificationdisabledevent_set.all().delete()
    deletion_event.participant.fcm_tokens.all().delete()
    deletion_event.participant.field_values.all().delete()
    deletion_event.participant.upload_trackers.all().delete()
    deletion_event.participant.scheduled_events.all().delete()
    deletion_event.participant.archived_events.all().delete()
    deletion_event.participant.intervention_dates.all().delete()
    confirm_deleted(deletion_event)
    deletion_event.participant.update(deleted=True)


def delete_participant_data(deletion_event: ParticipantDeletionEvent):
    """ Deletes all files on S3 for a participant. """
    for page_of_files in all_participant_file_paths(deletion_event.participant):
        # The dev is Extremely Aware that s3_list_versions call Could just return the raw boto3-
        # formatted list of dicts, and that that is the form they are received in. We. Do. Not.
        # Care. Instead we choose the the path of valor: hating boto3 so much that we will repack
        # the data into a structure that makes sense and then unpack it. Overhead is negligible.
        s3_delete_many_versioned(page_of_files)
        # If it doesn't raise an error then all the files were deleted.
        deletion_event.files_deleted_count += len(page_of_files)
        deletion_event.save()  # ! updates the event's last_updated, indicating deletion is running.


def confirm_deleted(deletion_event: ParticipantDeletionEvent):
    """ Tests all locations for files and database entries, raises AssertionError if any are found. """
    deletion_event.save()  # mark the event as processing...
    keys, base, chunks_prefix, problem_uploads = get_all_file_path_prefixes(deletion_event.participant)
    for _ in s3_list_files(keys, as_generator=True):
        raise AssertionError(f"still files present in {keys}")
    for _ in s3_list_files(base, as_generator=True):
        raise AssertionError(f"still files present in {base}")
    for _ in s3_list_files(chunks_prefix, as_generator=True):
        raise AssertionError(f"still files present in {chunks_prefix}")
    for _ in s3_list_files(problem_uploads, as_generator=True):
        raise AssertionError(f"still files present in {problem_uploads}")
    
    # MAKE SURE TO UPDATE TESTS IF YOU ADD MORE RELATIONS TO THIS LIST
    if deletion_event.participant.chunk_registries.exists():
        raise AssertionError("still have database entries for chunk_registries")
    if deletion_event.participant.summarystatisticdaily_set.exists():
        raise AssertionError("still have database entries for summarystatisticdaily")
    if deletion_event.participant.lineencryptionerror_set.exists():
        raise AssertionError("still have database entries for lineencryptionerror")
    if deletion_event.participant.iosdecryptionkey_set.exists():
        raise AssertionError("still have database entries for iosdecryptionkey")
    if deletion_event.participant.foresttask_set.exists():
        raise AssertionError("still have database entries for foresttask")
    if deletion_event.participant.encryptionerrormetadata_set.exists():
        raise AssertionError("still have database entries for encryptionerrormetadata")
    if deletion_event.participant.files_to_process.exists():
        raise AssertionError("still have database entries for files_to_process")
    if deletion_event.participant.pushnotificationdisabledevent_set.exists():
        raise AssertionError("still have database entries for pushnotificationdisabledevent")
    if deletion_event.participant.fcm_tokens.exists():
        raise AssertionError("still have database entries for fcm tokens (fcm history)")
    if deletion_event.participant.field_values.exists():
        raise AssertionError("still have database entries for participant field values")
    if deletion_event.participant.upload_trackers.exists():
        raise AssertionError("still have database entries for upload_trackers")
    if deletion_event.participant.intervention_dates.exists():
        raise AssertionError("still have database entries for intervention_dates")
    if deletion_event.participant.scheduled_events.exists():
        raise AssertionError("still have database entries for scheduled_events")
    if deletion_event.participant.archived_events.exists():
        raise AssertionError("still have database entries for archived_events")
    
    # mark the deletion event as _confirmed_ completed
    deletion_event.purge_confirmed_time = timezone.now()
    deletion_event.save()


def all_participant_file_paths(participant: Participant) -> List[Tuple[str, str]]:
    """ Generator, iterates over over all files for a participant, yields pages of 100 file_paths
    and version ids at a time. """
    many_file_version_ids = []
    
    # there will inevitably be more than these sets of files, using chain for flexibility
    for s3_prefix in itertools.chain(get_all_file_path_prefixes(participant)):
        for key_path_version_id_tuple in s3_list_versions(s3_prefix):
            many_file_version_ids.append(key_path_version_id_tuple)
            # yield a page of files, reset page
            if len(many_file_version_ids) % DELETION_PAGE_SIZE == 0:
                yield many_file_version_ids
                print(many_file_version_ids)
                many_file_version_ids = []
    
    # yield any overflow files
    if many_file_version_ids:
        yield many_file_version_ids


def get_all_file_path_prefixes(participant: Participant) -> Tuple[Tuple[str, str]]:
    """ The singular canonical location of all locations whhre participant data may be stored. """
    base = participant.study.object_id + "/" + participant.patient_id + "/"
    chunks_prefix = CHUNKS_FOLDER + "/" + base
    problem_uploads = PROBLEM_UPLOADS + "/" + base
    # this one is two files at most without a trailing slash
    keys = participant.study.object_id + "/keys/" + participant.patient_id
    return keys, base, chunks_prefix, problem_uploads
