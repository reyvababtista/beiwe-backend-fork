from django.utils import timezone

from services.celery_push_notifications import get_surveys_and_schedules
from tests.common import CommonTestCase


class TestCelery(CommonTestCase):
    pass


class TestGetSurveysAndSchedules(TestCelery):
    
    def test_empty_db(self):
        surveys, schedules, patientids = get_surveys_and_schedules(timezone.now())
        self.assertEqual(surveys, {})
        self.assertEqual(schedules, {})
        self.assertEqual(patientids, {})
