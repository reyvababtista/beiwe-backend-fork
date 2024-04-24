# trunk-ignore-all(bandit/B101)
from datetime import date

from constants.user_constants import ResearcherRole
from tests.common import ResearcherSessionTest


#
## participant_pages
#


# FIXME: implement more tests of this endpoint, it is complex.
class TestNotificationHistory(ResearcherSessionTest):
    ENDPOINT_NAME = "participant_pages.notification_history"
    
    def test_1(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self.generate_archived_event(self.default_survey, self.default_participant)
        self.smart_get_status_code(200, self.session_study.id, self.default_participant.patient_id)
    
    def test_0(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        # self.generate_archived_event(self.default_survey, self.default_participant)
        self.smart_get_status_code(200, self.session_study.id, self.default_participant.patient_id)
    
    # we need to hit all the logic possibilities for the heartbeat "pagination", mostly for coverage
    def test_50_100_200_210(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self.generate_participant_action_log() # this will be before everything, last page
        # the first query hits logic for a first page of exactly less than 100
        self.bulk_generate_archived_events(50, self.default_survey, self.default_participant)
        self.smart_get_status_code(200, self.session_study.id, self.default_participant.patient_id)
        # need to generate more for the followup tests
        self.bulk_generate_archived_events(60, self.default_survey, self.default_participant)
        self.generate_participant_action_log() # this will be in the middle of page two
        self.bulk_generate_archived_events(100, self.default_survey, self.default_participant)
        self.generate_participant_action_log() # this will be in at the top of page one
        # The first action log is on the last page now
        # the first query hits logic for a first page of exactly 100
        self.smart_get_status_code(200, self.session_study.id, self.default_participant.patient_id)
        # the second query hits logic for a not-first page of exactly 100
        self.smart_get_status_code(200, self.session_study.id, self.default_participant.patient_id, data=dict(page=2))
        # the third query hits logic for a not-first page of less than 100
        self.smart_get_status_code(200, self.session_study.id, self.default_participant.patient_id, data=dict(page=3))
    

class TestParticipantPage(ResearcherSessionTest):
    ENDPOINT_NAME = "participant_pages.participant_page"
    REDIRECT_ENDPOINT_NAME = "participant_pages.participant_page"
    
    def test_get(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        # This isn't a pure redirect endpoint, we need to test for a 200
        self.easy_get(
            self.ENDPOINT_NAME,
            status_code=200,
            study_id=self.session_study.id,
            patient_id=self.default_participant.patient_id
        )
    
    def test_post_with_bad_parameters(self):
        # test bad study id and bad patient id
        self.set_session_study_relation(ResearcherRole.study_admin)
        ret = self.smart_post(self.session_study.id, "invalid_patient_id")
        self.assertEqual(ret.status_code, 404)
        ret = self.smart_post(0, self.default_participant.patient_id)
        self.assertEqual(ret.status_code, 404)
    
    def test_custom_field_update(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        study_field = self.generate_study_field(self.session_study, "obscure_name_of_study_field")
        # intervention_date = self.default_unpopulated_intervention_date  # create a single intervention with no time
        self.assertFalse(self.default_participant.field_values.exists())
        
        # the post parameter here is  bit strange, literally it is like "field6" with a db pk
        post_param_name = "field" + str(study_field.id)
        self.smart_post_redirect(
            self.session_study.id, self.default_participant.patient_id,
            **{post_param_name: "any string value"}
        )
        self.assertEqual(self.default_participant.field_values.count(), 1)
        field_value = self.default_participant.field_values.first()
        self.assertEqual(field_value.field, study_field)
        self.assertEqual(field_value.value, "any string value")
    
    def test_intervention_update(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        intervention_date = self.default_unpopulated_intervention_date  # create a single intervention with no time
        self.assertEqual(intervention_date.date, None)
        # the post parameter here is  bit strange, literally it is like "intervention6" with a db pk
        post_param_name = "intervention" + str(intervention_date.intervention.id)
        self.smart_post_redirect(
            self.session_study.id, self.default_participant.patient_id,
            **{post_param_name: "2020-01-01"}
        )
        intervention_date.refresh_from_db()
        self.assertEqual(intervention_date.date, date(2020, 1, 1))
    
    def test_bad_date_1(self):
        self._test_intervention_update_with_bad_date("2020/01/01")
    
    def test_bad_date_2(self):
        self._test_intervention_update_with_bad_date("31/01/2020")
    
    def test_bad_date_3(self):
        self._test_intervention_update_with_bad_date("01/31/2020")
    
    def _test_intervention_update_with_bad_date(self, date_string: str):
        self.set_session_study_relation(ResearcherRole.study_admin)
        intervention_date = self.default_unpopulated_intervention_date  # create a single intervention with no time
        self.assertEqual(intervention_date.date, None)
        # the post parameter here is  bit strange, literally it is like "intervention6" with a db pk
        post_param_name = "intervention" + str(intervention_date.intervention.id)
        self.smart_post_redirect(
            self.session_study.id, self.default_participant.patient_id,
            **{post_param_name: date_string}
        )
        intervention_date.refresh_from_db()
        self.assertEqual(intervention_date.date, None)
        page = self.easy_get(
            self.ENDPOINT_NAME,
            status_code=200,
            study_id=self.session_study.id,
            patient_id=self.default_participant.patient_id
        ).content
        self.assert_present(
            'Invalid date format, please use the date selector or YYYY-MM-DD.', page
        )


class TestParticipantExperimentsPage(ResearcherSessionTest):
    ENDPOINT_NAME = "participant_pages.experiments_page"
    
    # this tests that the ParticipantExperimentForm doesn't crash, that's it.
    def test_get(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        x = self.easy_get(
            self.ENDPOINT_NAME,
            status_code=200,
            study_id=self.session_study.id,
            patient_id=self.default_participant.patient_id
        )
        assert x  # assert its not empty
