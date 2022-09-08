from constants.schedule_constants import EMPTY_WEEKLY_SURVEY_TIMINGS
from database.schedule_models import BadWeekllyCount, WeeklySchedule
from libs.schedules import NoSchedulesException, export_weekly_survey_timings, get_next_weekly_event_and_schedule
from tests.common import CommonTestCase


from pprint import pprint


MIDNIGHT_EVERY_DAY = lambda: [[0], [0], [0], [0], [0], [0], [0]]


class TestSchedules(CommonTestCase):
    
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
        self.assertEqual(timings, [[0], [0], [0], [0], [0], [0], [0]])
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
        # for lengsths of litsts of ints 1-10 assert that the appropriate error is raised
        for i in range(1, 10):
            timings = [[0] for _ in range(i)]
            if len(timings) != 7:
                self.assertRaises(
                    BadWeekllyCount, WeeklySchedule.create_weekly_schedules, timings, self.default_survey
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