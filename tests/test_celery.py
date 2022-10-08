from datetime import timedelta
from unittest.mock import MagicMock, patch

import time_machine
from django.utils import timezone

from constants.testing_constants import OCT_6_NOON_2022, OCT_20_NOON_2022
from database.schedule_models import ScheduledEvent
from services.celery_push_notifications import get_surveys_and_schedules
from tests.common import CommonTestCase


class TestCelery(CommonTestCase):
    pass


class TestGetSurveysAndSchedules(TestCelery):
    
    def test_empty_db(self):
        self.validate_no_schedules()
    
    def validate_no_schedules(self):
        surveys, schedules, patient_ids = get_surveys_and_schedules(timezone.now())
        self.assertEqual(surveys, {})
        self.assertEqual(schedules, {})
        self.assertEqual(patient_ids, {})
    
    def validate_basics(self, schedule: ScheduledEvent):
        surveys, schedules, patient_ids = get_surveys_and_schedules(timezone.now())
        self.assertEqual(surveys, {self.DEFAULT_FCM_TOKEN: [self.DEFAULT_SURVEY_OBJECT_ID]})
        self.assertEqual(schedules, {self.DEFAULT_FCM_TOKEN: [schedule.pk]})
        self.assertEqual(patient_ids, {self.DEFAULT_FCM_TOKEN: self.DEFAULT_PARTICIPANT_NAME})
    
    # just a placeholder for future work, send_notification not actually called in this test
    @patch('services.celery_push_notifications.send_notification')
    def test_absolute_success(self, send_notification: MagicMock):
        send_notification.return_value = None
        
        self.populate_default_fcm_token
        the_past = timezone.now() + timedelta(days=-5)
        # an absolute survey 5 days in the past
        schedule = self.generate_easy_absolute_schedule_event_with_schedule(the_past)
        self.validate_basics(schedule)
    
    def test_absolute_fail(self):
        self.populate_default_fcm_token
        future = timezone.now() + timedelta(days=5)
        # an absolute survey 5 days in the future
        self.generate_easy_absolute_schedule_event_with_schedule(future)
        self.validate_no_schedules()
    
    def test_relative_success(self):
        self.populate_default_fcm_token
        # a relative survey 5 days in the past
        schedule = self.generate_easy_relative_schedule_event_with_schedule(timedelta(days=-5))
        surveys, schedules, patient_ids = get_surveys_and_schedules(timezone.now())
        self.validate_basics(schedule)
    
    def test_relative_failure(self):
        self.populate_default_fcm_token
        # a relative survey 5 days in the past
        self.generate_easy_relative_schedule_event_with_schedule(timedelta(days=5))
        self.validate_no_schedules()
    
    @time_machine.travel(OCT_6_NOON_2022)
    def test_weekly_success(self):
        self.populate_default_fcm_token
        # a weekly survey, on a friday, sunday is the zero-index; I hate it more than you.
        schedule, count_created = self.generate_a_real_weekly_schedule_event_with_schedule(5)
        self.assertEqual(count_created, 1)
        with time_machine.travel(OCT_20_NOON_2022):
            self.validate_basics(schedule)
    
    @time_machine.travel(OCT_6_NOON_2022)
    def test_weekly_in_future_fails(self):
        self.populate_default_fcm_token
        # a weekly survey, on a friday, sunday is the zero-index; I hate it more than you.
        schedule, count_created = self.generate_a_real_weekly_schedule_event_with_schedule(5)
        self.assertEqual(count_created, 1)
        self.validate_no_schedules()
