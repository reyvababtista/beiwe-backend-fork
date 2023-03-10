import itertools
from typing import List, Tuple

from django.utils import timezone

from constants.common_constants import PROBLEM_UPLOADS
from constants.data_processing_constants import CHUNKS_FOLDER
from database.user_models_participant import Participant, ParticipantDeletionEvent
from libs.s3 import s3_delete_many_versioned, s3_list_files, s3_list_versions
from libs.security import generate_easy_alphanumeric_string

DELETION_PAGE_SIZE = 250


def add_particpiant_for_deletion(participant: Participant):
    """ adds a participant to the deletion queue. """
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
    confirm_deleted(deletion_event)


def delete_participant_data(deletion_event: ParticipantDeletionEvent):
    for page_of_files in enumerate(all_participant_file_paths(deletion_event.participant)):
        # we are Extremely aware that s3_list_versions could just return the correct boto3-formatted
        # list of dicts, and in fact that is the form they are received in. We Do Not Care. Instead
        # we choose to hate boto3. The repacking overhead is negligible.
        s3_delete_many_versioned(page_of_files)
        # If it doesn't raise an error then all the files were deleted.
        deletion_event.files_deleted_count += len(page_of_files)
        deletion_event.save()  # ! updates the event's last_updated, indicating deletion is running.


def confirm_deleted(deletion_event: ParticipantDeletionEvent):
    deletion_event.save()  # mark the event as processing...
    base, chunks_prefix, problem_uploads = get_all_file_path_prefixes(deletion_event.participant)
    files_base = s3_list_files(base)
    print("files_base", files_base)
    if not files_base == []:
        raise AssertionError(f"still files present in {base}")
    files_chunks_prefix = s3_list_files(chunks_prefix)
    print("files_chunks_prefix", files_chunks_prefix)
    if not files_chunks_prefix == []:
        raise AssertionError(f"still files present in {chunks_prefix}")
    files_problem_uploads = s3_list_files(problem_uploads)
    print("files_problem_uploads", files_problem_uploads)
    if not files_problem_uploads == []:
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
    # the singular canonical location of all locations whhre participant data may be stored.
    base = participant.study.object_id + "/" + participant.patient_id + "/"
    chunks_prefix = CHUNKS_FOLDER + "/" + base
    problem_uploads = PROBLEM_UPLOADS + "/" + base
    return base, chunks_prefix, problem_uploads