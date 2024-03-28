import time
import typing
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import dateutil
from dateutil.tz import gettz
from django.utils import timezone

from api.study_api import determine_registered_status
from constants.schedule_constants import EMPTY_WEEKLY_SURVEY_TIMINGS
from constants.testing_constants import MIDNIGHT_EVERY_DAY
from constants.user_constants import ACTIVE_PARTICIPANT_FIELDS
from database.data_access_models import IOSDecryptionKey
from database.profiling_models import EncryptionErrorMetadata, LineEncryptionError, UploadTracking
from database.schedule_models import BadWeeklyCount, WeeklySchedule
from database.user_models_participant import (AppHeartbeats, AppVersionHistory,
    DeviceStatusReportHistory, Participant, ParticipantActionLog, ParticipantDeletionEvent,
    PushNotificationDisabledEvent)
from libs.file_processing.utility_functions_simple import BadTimecodeError, binify_from_timecode
from libs.forest_utils import get_forest_git_hash
from libs.participant_purge import (confirm_deleted, get_all_file_path_prefixes,
    run_next_queued_participant_data_deletion)
from libs.schedules import (export_weekly_survey_timings, get_next_weekly_event_and_schedule,
    NoSchedulesException)
from tests.common import CommonTestCase


# trunk-ignore-all(ruff/B018,bandit/B101)
NoneType = type(None)  # noqa


# timezones should be compared using the 'is' operator
THE_ONE_TRUE_TIMEZONE = gettz("America/New_York")
THE_OTHER_ACCEPTABLE_TIMEZONE = gettz("UTC")

COUNT_OF_PATHS_RETURNED_FROM_GET_ALL_FILE_PATH_PREFIXES = 4

# Decorator for class instance methods that injects these three mocks, used in data purge tests.
# @patch('libs.participant_purge.s3_list_files')
# @patch('libs.participant_purge.s3_delete_many_versioned')
# @patch('libs.participant_purge.s3_list_versions')
# These patches are for the database table deletions.  s3_list_files specifically would result in an
# assertion error stating that the base s3 file path is not empty, so we patch that in the rest of
# the tests, which are database purge tests.
def data_purge_mock_s3_calls(func):
    s3_delete_many_versioned = patch('libs.participant_purge.s3_delete_many_versioned')
    s3_list_files = patch('libs.participant_purge.s3_list_files')
    s3_list_versions = patch('libs.participant_purge.s3_list_versions')
    s3_list_files.return_value = []
    s3_list_versions.return_value = []
    s3_delete_many_versioned.return_value = []
    def wrapper(self, *args, **kwargs):
        with s3_delete_many_versioned, s3_list_files, s3_list_versions:
            return func(self, *args, **kwargs)
    return wrapper


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
        self.assertEqual(self.default_participant.deleted, True)
        self.assertEqual(self.default_participant.easy_enrollment, False)
        self.assertEqual(self.default_participant.permanently_retired, True)
        self.assertEqual(self.default_participant.device_id, "")
        self.assertEqual(self.default_participant.os_type, "")
    
    def assert_correct_s3_parameters_called(
        self,
        s3_list_versions: MagicMock,
        s3_list_files: MagicMock,
        s3_delete_many_versioned: MagicMock,
        list_versions_count: int = COUNT_OF_PATHS_RETURNED_FROM_GET_ALL_FILE_PATH_PREFIXES,
        list_files_count: int = COUNT_OF_PATHS_RETURNED_FROM_GET_ALL_FILE_PATH_PREFIXES,
        delete_versioned_count: int = COUNT_OF_PATHS_RETURNED_FROM_GET_ALL_FILE_PATH_PREFIXES,
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
        
        path_keys, path_participant, path_chunked, path_problems = get_all_file_path_prefixes(self.default_participant)
        if list_files_count == COUNT_OF_PATHS_RETURNED_FROM_GET_ALL_FILE_PATH_PREFIXES:
            self.assertEqual(s3_list_files.call_args_list[0].args[0], path_keys)
            self.assertEqual(s3_list_files.call_args_list[1].args[0], path_participant)
            self.assertEqual(s3_list_files.call_args_list[2].args[0], path_chunked)
            self.assertEqual(s3_list_files.call_args_list[3].args[0], path_problems)
        if list_versions_count == COUNT_OF_PATHS_RETURNED_FROM_GET_ALL_FILE_PATH_PREFIXES:
            self.assertEqual(s3_list_versions.call_args_list[0].args[0], path_keys)
            self.assertEqual(s3_list_versions.call_args_list[1].args[0], path_participant)
            self.assertEqual(s3_list_versions.call_args_list[2].args[0], path_chunked)
            self.assertEqual(s3_list_versions.call_args_list[3].args[0], path_problems)
    
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
        # this should fail because the participant is not marked as deleted.
        self.assertRaises(AssertionError, self.assert_default_participant_end_state)
        self.assert_correct_s3_parameters_called(
            s3_list_versions, s3_list_files, s3_delete_many_versioned, list_files_count=1, delete_versioned_count=0)
        self.default_participant_deletion_event.refresh_from_db()
        self.assertIsNone(self.default_participant_deletion_event.purge_confirmed_time)
    
    @property
    def assert_confirm_deletion_raises_then_reset_last_updated(self):
        self.default_participant_deletion_event.refresh_from_db()
        last_updated = self.default_participant_deletion_event.last_updated
        self.assertRaises(AssertionError, confirm_deleted, self.default_participant_deletion_event)
        ParticipantDeletionEvent.objects.filter(
            pk=self.default_participant_deletion_event.pk).update(last_updated=last_updated)
    
    def test_assert_confirm_deletion_raises_then_reset_last_updated_works(self):
        class GoodError(Exception): pass
        text_1 ="this test should have raised an assertion error, " \
                "all database tests for TestParticipantDataDeletion invalidated."
        text_2 = text_1 + " (second instance)"
        text_1 = text_1 + " (first instance)"
        try:
            self.assert_confirm_deletion_raises_then_reset_last_updated
            raise GoodError(text_1)
        except AssertionError:
            FALSE_IF_IT_FAILED = False
        except GoodError:
            FALSE_IF_IT_FAILED = True
        assert FALSE_IF_IT_FAILED, text_2
    
    @data_purge_mock_s3_calls
    def test_confirm_ChunkRegistry(self):
        self.default_participant_deletion_event
        self.default_chunkregistry
        self.assert_confirm_deletion_raises_then_reset_last_updated
        run_next_queued_participant_data_deletion()
        confirm_deleted(self.default_participant_deletion_event)  # errors means test failure
        
    @data_purge_mock_s3_calls
    def test_confirm_SummaryStatisticDaily(self):
        self.default_summary_statistic_daily
        self.assert_confirm_deletion_raises_then_reset_last_updated
        run_next_queued_participant_data_deletion()
        confirm_deleted(self.default_participant_deletion_event)
    
    @data_purge_mock_s3_calls
    def test_confirm_LineEncryptionError(self):
        LineEncryptionError.objects.create(
            base64_decryption_key="abc123",
            participant=self.default_participant,
            type=LineEncryptionError.PADDING_ERROR
        )
        self.assert_confirm_deletion_raises_then_reset_last_updated
        run_next_queued_participant_data_deletion()
        confirm_deleted(self.default_participant_deletion_event)
    
    @data_purge_mock_s3_calls
    def test_confirm_IOSDecryptionKey(self):
        IOSDecryptionKey.objects.create(
            participant=self.default_participant, base64_encryption_key="abc123", file_name="abc123"
        )
        self.assert_confirm_deletion_raises_then_reset_last_updated
        run_next_queued_participant_data_deletion()
        confirm_deleted(self.default_participant_deletion_event)
    
    @data_purge_mock_s3_calls
    def test_confirm_ForestTask(self):
        self.generate_forest_task()
        self.assert_confirm_deletion_raises_then_reset_last_updated
        run_next_queued_participant_data_deletion()
        confirm_deleted(self.default_participant_deletion_event)
    
    @data_purge_mock_s3_calls
    def test_confirm_EncryptionErrorMetadata(self):
        EncryptionErrorMetadata.objects.create(
            file_name="a", total_lines=1, number_errors=1, error_lines="a", error_types="a", participant=self.default_participant
        )
        self.assert_confirm_deletion_raises_then_reset_last_updated
        run_next_queued_participant_data_deletion()
        confirm_deleted(self.default_participant_deletion_event)
    
    @data_purge_mock_s3_calls
    def test_confirm_FileToProcess(self):
        self.generate_file_to_process("a_path")
        self.assert_confirm_deletion_raises_then_reset_last_updated
        run_next_queued_participant_data_deletion()
        confirm_deleted(self.default_participant_deletion_event)
    
    @data_purge_mock_s3_calls
    def test_confirm_PushNotificationDisabledEvent(self):
        PushNotificationDisabledEvent.objects.create(participant=self.default_participant, count=1)
        self.assert_confirm_deletion_raises_then_reset_last_updated
        run_next_queued_participant_data_deletion()
        confirm_deleted(self.default_participant_deletion_event)
    
    @data_purge_mock_s3_calls
    def test_confirm_ParticipantFCMHistory(self):
        self.populate_default_fcm_token
        self.assert_confirm_deletion_raises_then_reset_last_updated
        run_next_queued_participant_data_deletion()
        confirm_deleted(self.default_participant_deletion_event)
    
    @data_purge_mock_s3_calls
    def test_confirm_ParticipantFieldValue(self):
        self.default_participant_field_value
        self.assert_confirm_deletion_raises_then_reset_last_updated
        run_next_queued_participant_data_deletion()
        confirm_deleted(self.default_participant_deletion_event)
    @data_purge_mock_s3_calls
    def test_confirm_UploadTracking(self):
        UploadTracking.objects.create(
            file_path=" ", file_size=0, timestamp=timezone.now(), participant=self.default_participant
        )
        self.assert_confirm_deletion_raises_then_reset_last_updated
        run_next_queued_participant_data_deletion()
        confirm_deleted(self.default_participant_deletion_event)
    
    @data_purge_mock_s3_calls
    def test_confirm_ScheduledEvent(self):
        sched_event = self.generate_a_real_weekly_schedule_event_with_schedule()[0]
        self.assert_confirm_deletion_raises_then_reset_last_updated
        sched_event.archive(self_delete=True, status="deleted", created_on=timezone.now())
    
    @data_purge_mock_s3_calls
    def test_confirm_ArchivedEvent(self):
        # its easiest to use a scheduled event to create an archived event...
        sched_event = self.generate_a_real_weekly_schedule_event_with_schedule()[0]
        sched_event.archive(self_delete=True, status="deleted", created_on=timezone.now())
        self.assert_confirm_deletion_raises_then_reset_last_updated
        run_next_queued_participant_data_deletion()
        confirm_deleted(self.default_participant_deletion_event)
    
    @data_purge_mock_s3_calls
    def test_confirm_InterventionDate(self):
        self.default_populated_intervention_date
        self.assert_confirm_deletion_raises_then_reset_last_updated
        run_next_queued_participant_data_deletion()
        confirm_deleted(self.default_participant_deletion_event)
    
    @data_purge_mock_s3_calls
    def test_confirm_AppHeartbeats(self):
        AppHeartbeats.create(self.default_participant, timezone.now())
        self.assert_confirm_deletion_raises_then_reset_last_updated
        run_next_queued_participant_data_deletion()
        confirm_deleted(self.default_participant_deletion_event)
        
    @data_purge_mock_s3_calls
    def test_confirm_ParticipantActionLog(self):
        # this test is weird, we create an action log inside the deletion event.
        
        self.default_participant_deletion_event
        self.assertEqual(ParticipantActionLog.objects.count(), 0)
        run_next_queued_participant_data_deletion()
        self.assertEqual(ParticipantActionLog.objects.count(), 2)
    
    @data_purge_mock_s3_calls
    def test_confirm_DeviceStatusReportHistory(self):
        self.default_participant.generate_device_status_report_history("some_endpoint_path")
        self.default_participant_deletion_event
        self.assertEqual(DeviceStatusReportHistory.objects.count(), 1)
        run_next_queued_participant_data_deletion()
        self.assertEqual(DeviceStatusReportHistory.objects.count(), 0)
    
    @data_purge_mock_s3_calls
    def test_confirm_AppVersionHistory(self):
        self.default_participant.update_only(last_version_code="10")
        self.default_participant.generate_app_version_history("11")
        self.default_participant_deletion_event
        self.assertEqual(AppVersionHistory.objects.count(), 1)
        run_next_queued_participant_data_deletion()
        self.assertEqual(AppVersionHistory.objects.count(), 0)
    
    def test_for_all_related_fields(self):
        # This test will fail whenever there is a new related model added to the codebase.
        for model in Participant._meta.related_objects:
            model_name = model.related_model.__name__
            # but not the deletion operation that's kinda important...
            if model_name == "ParticipantDeletionEvent":
                continue
            assert hasattr(TestParticipantDataDeletion, f"test_confirm_{model_name}"), \
                f"missing test_confirm_{model_name} for {model_name}"


class TestParticipantTimeZone(CommonTestCase):
    
    def test_defaults(self):
        # test the default is applied
        self.assertEqual(self.default_participant.timezone_name, "America/New_York")
        # test that the model default is actually America/New_York
        self.assertEqual(Participant._meta.get_field("timezone_name").default, "America/New_York")
        # test that timezone returns a timezone of America/New_York
        # test that the object returned is definitely the DATEUTIL timezone object
        # THIS TEST MAY NOT PASS ON NON-LINUX COMPUTERS? Will have to test mac, we don't actually support raw windows.
        self.assertIsInstance(self.default_participant.timezone, dateutil.tz.tzfile)
        # test that the timezone is the expected object
        self.assertIs(self.default_participant.timezone, THE_ONE_TRUE_TIMEZONE)
    
    def test_try_null(self):
        # discovered weird behavior where a None passed into gettz returns utc.
        try:
            self.default_participant.try_set_timezone(None)
            self.fail("should have raised a TypeError")
        except TypeError:
            pass  # it should raise a TypeError
    
    def test_try_empty_string(self):
        # discovered weird behavior where the empty string passed into gettz returns utc.
        try:
            self.default_participant.try_set_timezone("")
            self.fail("should have raised a TypeError")
        except TypeError:
            pass  # it should raise a TypeError
    
    def test_try_bad_string(self):
        # the unknown_timezone flag should be true at the start and the end.
        p = self.default_participant
        self.assertEqual(p.timezone_name, "America/New_York")
        self.assertIs(p.timezone, THE_ONE_TRUE_TIMEZONE)
        self.assertEqual(p.unknown_timezone, True)  # A
        p.try_set_timezone("a bad string")
        # behavior should be to grab the study's timezone name, which for tests was unexpectedly UTC...
        self.assertEqual(p.timezone_name, "UTC")
        self.assertIs(p.timezone, THE_OTHER_ACCEPTABLE_TIMEZONE)
        self.assertEqual(p.unknown_timezone, True)  # A
    
    def test_try_bad_string_resets_unknown_timezone(self):
        p = self.default_participant
        p.update_only(unknown_timezone=False)  # force value to false
        self.assertEqual(p.timezone_name, "America/New_York")
        self.assertIs(p.timezone, THE_ONE_TRUE_TIMEZONE)
        self.assertEqual(p.unknown_timezone, False)  # A
        p.try_set_timezone("a bad string")
        # behavior should be to grab the study's timezone name, which for tests was unexpectedly UTC...
        self.assertEqual(p.timezone_name, "UTC")
        self.assertIs(p.timezone, THE_OTHER_ACCEPTABLE_TIMEZONE)
        self.assertEqual(p.unknown_timezone, True)  # B
    
    def test_same_timezone_name_still_updates_unknown_timezone_flag(self):
        p = self.default_participant
        last_update = p.last_updated
        self.assertEqual(p.timezone_name, "America/New_York")
        self.assertIs(p.timezone, THE_ONE_TRUE_TIMEZONE)
        self.assertEqual(p.unknown_timezone, True)  # A
        p.try_set_timezone("America/New_York")
        self.assertEqual(p.timezone_name, "America/New_York")
        self.assertIs(p.timezone, THE_ONE_TRUE_TIMEZONE)
        self.assertEqual(p.unknown_timezone, False)  # B
        self.assertEqual(p.last_updated, last_update)
    
    def test_valid_input(self):
        # should change both the timezone and the unknown_timezone flag
        p = self.default_participant
        last_update = p.last_updated
        self.assertEqual(p.timezone_name, "America/New_York")
        self.assertIs(p.timezone, THE_ONE_TRUE_TIMEZONE)
        self.assertEqual(p.unknown_timezone, True)
        p.try_set_timezone("America/Los_Angeles")
        self.assertEqual(p.timezone_name, "America/Los_Angeles")
        self.assertIs(p.timezone, gettz("America/Los_Angeles"))
        self.assertEqual(p.unknown_timezone, False)
        self.assertEqual(p.last_updated, last_update)


class TestParticipantActive(CommonTestCase):
    """ We need a test for keeping the status of "this is an active participant" up to date across
    some distinct code paths """
    
    def test_determine_registered_status(self):
        # determine_registered_status is code in an important optimized codepath for the study page,
        # it can't be factored down to a call on a Participant object because it operates on contents
        # out of a values_list query.  It also deals with creating strings and needs to know if the
        # registered field is set (which we don't care about in other places).
        annotes = determine_registered_status.__annotations__
        correct_annotations = {
            'now': datetime,
            'registered': bool,
            'last_upload': typing.Union[datetime, NoneType],  # can't import NoneType...
            'last_get_latest_surveys': typing.Union[datetime, NoneType],
            'last_set_password': typing.Union[datetime, NoneType],
            'last_set_fcm_token': typing.Union[datetime, NoneType],
            'last_get_latest_device_settings': typing.Union[datetime, NoneType],
            'last_register_user': typing.Union[datetime, NoneType]
        }
        self.assertDictEqual(annotes, correct_annotations)
    
    def test_participant_is_active_one_week_false(self):
        # this test is self referential...
        now = timezone.now()
        more_than_a_week_ago = now - timedelta(days=8)
        p = self.default_participant
        for field_outer in ACTIVE_PARTICIPANT_FIELDS:
            for field_inner in ACTIVE_PARTICIPANT_FIELDS:
                if field_inner != field_outer:
                    setattr(p, field_inner, None)
                else:
                    setattr(p, field_inner, more_than_a_week_ago)
            self.assertFalse(p.is_active_one_week)
    
    def test_participant_is_active_one_week_true(self):
        # this test is self referential...
        now = timezone.now()
        less_than_a_week_ago = now - timedelta(days=6)
        p = self.default_participant
        for field_outer in ACTIVE_PARTICIPANT_FIELDS:
            for field_inner in ACTIVE_PARTICIPANT_FIELDS:
                if field_inner != field_outer:
                    setattr(p, field_inner, None)
                else:
                    setattr(p, field_inner, less_than_a_week_ago)
            self.assertTrue(p.is_active_one_week)


class TestForestHash(unittest.TestCase):
    def test_get_forest_git_hash(self):
        hash = get_forest_git_hash()
        self.assertNotEqual(hash, "")
