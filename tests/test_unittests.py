import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from constants.schedule_constants import EMPTY_WEEKLY_SURVEY_TIMINGS
from constants.testing_constants import MIDNIGHT_EVERY_DAY
from database.data_access_models import IOSDecryptionKey
from database.profiling_models import EncryptionErrorMetadata, LineEncryptionError
from database.schedule_models import BadWeeklyCount, WeeklySchedule
from database.user_models_participant import Participant, ParticipantDeletionEvent
from libs.file_processing.exceptions import BadTimecodeError
from libs.file_processing.utility_functions_simple import binify_from_timecode
from libs.participant_purge import confirm_deleted, run_next_queued_participant_data_deletion
from libs.schedules import (export_weekly_survey_timings, get_next_weekly_event_and_schedule,
    NoSchedulesException)
from tests.common import CommonTestCase


class TestTimingsSchedules(CommonTestCase):
    
    def test_immutable_defaults(self):
        # assert that this variable creates lists anew.
        self.assertIsNot(EMPTY_WEEKLY_SURVEY_TIMINGS(), EMPTY_WEEKLY_SURVEY_TIMINGS())
    
    def test_export_weekly_survey_timings_no_schedules(self):
        # assert function only works with populated weekly schedules
        try:
            get_next_weekly_event_and_schedule(self.default_survey)
        except NoSchedulesException as e:
            some_no_schedules_exception = e
        self.assertIn("some_no_schedules_exception", locals())
    
    def test_export_weekly_survey_timings(self):
        # assert that the timings output from no-schedules survey are the empty timings dict
        self.assertEqual(
            EMPTY_WEEKLY_SURVEY_TIMINGS(), export_weekly_survey_timings(self.default_survey)
        )
    
    def test_each_day_of_week(self):
        # test that each weekday
        timings = EMPTY_WEEKLY_SURVEY_TIMINGS()
        for day_of_week in range(0, 7):
            self.generate_weekly_schedule(self.default_survey, day_of_week=day_of_week)
            timings[day_of_week].append(0)  # time of day defaults to zero
        # assert tehre are 7 weekly surveys, that they are one per day, at midnight (0)
        self.assertEqual(WeeklySchedule.objects.count(), 7)
        self.assertEqual(timings, MIDNIGHT_EVERY_DAY())
        self.assertEqual(timings, export_weekly_survey_timings(self.default_survey))
    
    def test_create_weekly_schedules(self):
        # assert we handle no surveys case
        WeeklySchedule.create_weekly_schedules(EMPTY_WEEKLY_SURVEY_TIMINGS(), self.default_survey)
        self.assertEqual(WeeklySchedule.objects.count(), 0)
        # assert we created a survey for every week
        WeeklySchedule.create_weekly_schedules(MIDNIGHT_EVERY_DAY(), self.default_survey)
        self.assertEqual(WeeklySchedule.objects.count(), 7)
        self.assertEqual(
            sorted(list(WeeklySchedule.objects.values_list("day_of_week", flat=True))),
            list(range(0, 7)),
        )
    
    def test_create_weekly_schedules_details(self):
        timings = EMPTY_WEEKLY_SURVEY_TIMINGS()
        timings[0].append(3600 + 120)  # schedule 1am and 1 minute on sunday
        WeeklySchedule.create_weekly_schedules(timings, self.default_survey)
        self.assertEqual(WeeklySchedule.objects.count(), 1)
        weekly = WeeklySchedule.objects.first()
        self.assertEqual(weekly.day_of_week, 0)
        self.assertEqual(weekly.hour, 1)
        self.assertEqual(weekly.minute, 2)
    
    def test_create_weekly_schedules_details_2(self):
        # as test_create_weekly_schedules_details, but we drop seconds because we only have minutes
        timings = EMPTY_WEEKLY_SURVEY_TIMINGS()
        timings[0].append(3600 + 120 + 1)  # schedule 1am and 1 minute and 1 second on sunday
        WeeklySchedule.create_weekly_schedules(timings, self.default_survey)
        self.assertEqual(WeeklySchedule.objects.count(), 1)
        weekly = WeeklySchedule.objects.first()
        self.assertEqual(weekly.day_of_week, 0)
        self.assertEqual(weekly.hour, 1)
        self.assertEqual(weekly.minute, 2)
    
    def test_create_weekly_schedules_bad_count(self):
        # for lengths of lists of ints 1-10 assert that the appropriate error is raised
        for i in range(1, 10):
            timings = [[0] for _ in range(i)]
            if len(timings) != 7:
                self.assertRaises(
                    BadWeeklyCount, WeeklySchedule.create_weekly_schedules, timings, self.default_survey
                )
            else:
                WeeklySchedule.create_weekly_schedules(timings, self.default_survey)
                self.assertEqual(WeeklySchedule.objects.count(), 7)
    
    def test_create_weekly_clears(self):
        # test that deleted surveys and empty timings lists delete stuff
        duplicates = WeeklySchedule.create_weekly_schedules(MIDNIGHT_EVERY_DAY(), self.default_survey)
        self.assertFalse(duplicates)
        self.assertEqual(WeeklySchedule.objects.count(), 7)
        duplicates = WeeklySchedule.create_weekly_schedules([], self.default_survey)
        self.assertFalse(duplicates)
        self.assertEqual(WeeklySchedule.objects.count(), 0)
        duplicates = WeeklySchedule.create_weekly_schedules(MIDNIGHT_EVERY_DAY(), self.default_survey)
        self.assertFalse(duplicates)
        self.assertEqual(WeeklySchedule.objects.count(), 7)
        self.default_survey.update(deleted=True)
        duplicates = WeeklySchedule.create_weekly_schedules(MIDNIGHT_EVERY_DAY(), self.default_survey)
        self.assertFalse(duplicates)
        self.assertEqual(WeeklySchedule.objects.count(), 0)
    
    def test_duplicates_return_value(self):
        timings = MIDNIGHT_EVERY_DAY()
        timings[0].append(0)
        duplicates = WeeklySchedule.create_weekly_schedules(timings, self.default_survey)
        self.assertTrue(duplicates)
        self.assertEqual(WeeklySchedule.objects.count(), 7)


class TestBinifyFromTimecode(unittest.TestCase):
    def test_binify_from_timecode_short_str(self):
        # str(int(time.mktime(datetime(2023, 1, 10, 2, 13, 7, 453914, tzinfo=dateutil.tz.UTC).timetuple()))
        self.assertEqual(binify_from_timecode('1673316787'), 464810)
    
    def test_binify_from_timecode_short_bytes(self):
        self.assertEqual(binify_from_timecode(b'1673316787'), 464810)
    
    def test_binify_from_timecode_long_bytes(self):
        self.assertEqual(binify_from_timecode(b'1673316787111'), 464810)
    
    def test_binify_from_timecode_long_str(self):
        # str(int(time.mktime(datetime(2023, 1, 10, 2, 13, 7, 453914, tzinfo=dateutil.tz.UTC).timetuple()))
        self.assertEqual(binify_from_timecode('1673316787222'), 464810)
    
    def test_binify_from_timecode_too_early(self):
        # should be 1 second too early
        self.assertRaises(BadTimecodeError, binify_from_timecode, b'1406851199')
    
    def test_binify_from_timecode_too_late(self):
        self.assertRaises(BadTimecodeError, binify_from_timecode, b'9999999999')
    
    def test_binify_from_timecode_91_days(self):
        timestamp = str(int(time.mktime((datetime.utcnow() + timedelta(days=91)).timetuple())))
        self.assertRaises(BadTimecodeError, binify_from_timecode, timestamp.encode())


class TestParticipantDataDeletion(CommonTestCase):
    
    def assert_default_participant_end_state(self):
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.deleted, False)
        self.assertEqual(self.default_participant.easy_enrollment, False)
        self.assertEqual(self.default_participant.unregistered, True)
        self.assertEqual(self.default_participant.device_id, "")
        self.assertEqual(self.default_participant.os_type, "")
    
    def assert_correct_s3_parameters_called(
        self,
        s3_list_versions: MagicMock,
        s3_list_files: MagicMock,
        s3_delete_many_versioned: MagicMock,
        list_versions_count: int = 3,
        list_files_count: int = 3,
        delete_versioned_count: int = 3,
    ):
        # sanity checks to save our butts
        self.assertEqual(s3_list_versions._mock_name, "s3_list_versions")
        self.assertEqual(s3_list_files._mock_name, "s3_list_files")
        self.assertEqual(s3_delete_many_versioned._mock_name, "s3_delete_many_versioned")
        self.assertEqual(s3_list_versions.call_count, list_versions_count)
        self.assertEqual(s3_list_files.call_count, list_files_count)
        # tests that call this function should implement their own assertions on the number of calls
        # to and parameters to s3_delete_many_versioned.
        self.assertEqual(s3_delete_many_versioned.call_count, delete_versioned_count)
        # check that all the paths were correct for the participant and study, this is a somewhat
        # tautological test, but its important to have something that breaks easily if the paths
        # change to ensure we get coverage on any new paths we might add
        study_id = self.default_participant.study.object_id
        patient_id = self.default_participant.patient_id
        path_participant = f'{study_id}/{patient_id}/'
        path_chunked = f'CHUNKED_DATA/{study_id}/{patient_id}/'
        path_problems = f'PROBLEM_UPLOADS/{study_id}/{patient_id}/'
        if list_files_count == 3:
            self.assertEqual(s3_list_files.call_args_list[0].args[0], path_participant)
            self.assertEqual(s3_list_files.call_args_list[1].args[0], path_chunked)
            self.assertEqual(s3_list_files.call_args_list[2].args[0], path_problems)
        if list_versions_count == 3:
            self.assertEqual(s3_list_versions.call_args_list[0].args[0], path_participant)
            self.assertEqual(s3_list_versions.call_args_list[1].args[0], path_chunked)
            self.assertEqual(s3_list_versions.call_args_list[2].args[0], path_problems)
    
    def test_no_participants_at_all(self):
        self.assertFalse(Participant.objects.exists())
        run_next_queued_participant_data_deletion()
        self.assertFalse(Participant.objects.exists())
    
    def test_no_participant_but_with_a_participant_in_the_db(self):
        last_update = self.default_participant.last_updated  # create!
        self.assertEqual(Participant.objects.count(), 1)
        self.assertEqual(ParticipantDeletionEvent.objects.count(), 0)
        run_next_queued_participant_data_deletion()
        self.assertEqual(Participant.objects.count(), 1)
        self.assertEqual(ParticipantDeletionEvent.objects.count(), 0)
        self.default_participant.refresh_from_db()
        self.assertEqual(last_update, self.default_participant.last_updated)
    
    #! REMINDER: ordering of these inserts parameters is in reverse order of declaration. You can
    #  confirm the correct mock target by looking at the _mock_name (or vars) of the mock object.
    @patch('libs.participant_purge.s3_delete_many_versioned', return_value=[])
    @patch('libs.participant_purge.s3_list_files', return_value=[])
    @patch('libs.participant_purge.s3_list_versions', return_value=[])
    def test_deleting_data_for_one_empty_participant(
        self, s3_list_versions: MagicMock, s3_list_files: MagicMock, s3_delete_many_versioned: MagicMock
    ):
        self.default_participant_deletion_event  # includes default_participant creation
        self.assertEqual(Participant.objects.count(), 1)
        run_next_queued_participant_data_deletion()
        self.assertEqual(Participant.objects.count(), 1)  # we don't actually delete the db object just the data...
        self.default_participant.refresh_from_db()
        self.assert_default_participant_end_state()
        self.assert_correct_s3_parameters_called(
            s3_list_versions, s3_list_files, s3_delete_many_versioned, delete_versioned_count=0
        )
        self.default_participant_deletion_event.refresh_from_db()
        self.assertEqual(self.default_participant_deletion_event.files_deleted_count, 0)
        self.assertIsInstance(self.default_participant_deletion_event.purge_confirmed_time, datetime)
    
    @patch('libs.participant_purge.s3_delete_many_versioned')
    @patch('libs.participant_purge.s3_list_files')
    @patch('libs.participant_purge.s3_list_versions')
    def test_deleting_errors_on_list(
        self, s3_list_versions: MagicMock, s3_list_files: MagicMock, s3_delete_many_versioned: MagicMock
    ):
        # s3_list_files should result in an assertion error stating that the base s3 file path is
        # not empty. in principle this may change the exact error, as long as it fails its working.
        s3_list_files.return_value = ["some_file"]
        self.default_participant_deletion_event
        self.assertRaises(AssertionError, run_next_queued_participant_data_deletion)
        self.assert_default_participant_end_state()
        self.assert_correct_s3_parameters_called(s3_list_versions, s3_list_files, s3_delete_many_versioned, list_files_count=1, delete_versioned_count=0)
        self.default_participant_deletion_event.refresh_from_db()
        self.assertIsNone(self.default_participant_deletion_event.purge_confirmed_time)
    
    # actually a unittest!
    @patch('libs.participant_purge.s3_list_files')
    def test_confirm_deleted(self, s3_list_files: MagicMock):
        # s3_list_files should result in an assertion error stating that the base s3 file path is not empty
        s3_list_files.return_value = []
        
        # ChunkRegistry
        self.default_chunkregistry
        self.assertRaises(AssertionError, confirm_deleted, self.default_participant_deletion_event)
        self.default_chunkregistry.delete()
        confirm_deleted(self.default_participant_deletion_event)  # errors means test failure
        
        # summary statistic
        self.default_summary_statistic_daily
        self.assertRaises(AssertionError, confirm_deleted, self.default_participant_deletion_event)
        self.default_summary_statistic_daily.delete()
        confirm_deleted(self.default_participant_deletion_event)
        
        # LineEncryptionError - we don't need test infrastructure these, we just do not care.
        LineEncryptionError.objects.create(
            base64_decryption_key="abc123",
            participant=self.default_participant,
            type=LineEncryptionError.PADDING_ERROR
        )
        self.assertRaises(AssertionError, confirm_deleted, self.default_participant_deletion_event)
        LineEncryptionError.objects.all().delete()
        confirm_deleted(self.default_participant_deletion_event)
        
        # IosDecryptionKey
        IOSDecryptionKey.objects.create(
            participant=self.default_participant, base64_encryption_key="abc123", file_name="abc123"
        )
        self.assertRaises(AssertionError, confirm_deleted, self.default_participant_deletion_event)
        IOSDecryptionKey.objects.all().delete()
        confirm_deleted(self.default_participant_deletion_event)
        
        task = self.generate_forest_task()
        self.assertRaises(AssertionError, confirm_deleted, self.default_participant_deletion_event)
        task.delete()
        confirm_deleted(self.default_participant_deletion_event)
        
        # EncryptionErrorMetadata
        EncryptionErrorMetadata.objects.create(
            file_name="a", total_lines=1, number_errors=1, error_lines="a", error_types="a", participant=self.default_participant
        )
        self.assertRaises(AssertionError, confirm_deleted, self.default_participant_deletion_event)
        EncryptionErrorMetadata.objects.all().delete()
        confirm_deleted(self.default_participant_deletion_event)
        
        # FileToProcess
        ftp = self.generate_file_to_process("a_path")
        self.assertRaises(AssertionError, confirm_deleted, self.default_participant_deletion_event)
        ftp.delete()
        confirm_deleted(self.default_participant_deletion_event)
