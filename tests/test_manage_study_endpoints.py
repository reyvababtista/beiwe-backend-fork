from constants.user_constants import ResearcherRole
from tests.common import ResearcherSessionTest


class TestToggleStudyEasyEnrollment(ResearcherSessionTest):
    ENDPOINT_NAME = "manage_study_endpoints.toggle_easy_enrollment_study"
    REDIRECT_ENDPOINT_NAME = "study_endpoints.edit_study"
    
    def test_site_admin(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        self._test_success()
    
    def test_study_admin(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self._test_success()
    
    def _test_success(self):
        self.assertFalse(self.default_study.easy_enrollment)
        self.smart_get_redirect(self.session_study.id)
        self.default_study.refresh_from_db()
        self.assertTrue(self.default_study.easy_enrollment)
    
    def test_researcher(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self._test_fail()
    
    def test_no_relation(self):
        self.session_researcher.study_relations.all().delete()  # should be redundant
        self._test_fail()
    
    def _test_fail(self):
        self.assertFalse(self.default_study.easy_enrollment)
        self.easy_get(self.ENDPOINT_NAME, status_code=403, study_id=self.session_study.id).content
        self.default_study.refresh_from_db()
        self.assertFalse(self.default_study.easy_enrollment)


# fixme: add user type tests
class TestRenameStudy(ResearcherSessionTest):
    ENDPOINT_NAME = "manage_study_endpoints.rename_study"
    REDIRECT_ENDPOINT_NAME = "study_endpoints.edit_study"
    
    def test(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        self.smart_post_redirect(self.session_study.id, new_study_name="hello!")
        self.session_study.refresh_from_db()
        self.assertEqual(self.session_study.name, "hello!")


# FIXME: add error cases to this test
class TestSetStudyTimezone(ResearcherSessionTest):
    ENDPOINT_NAME = "manage_study_endpoints.set_study_timezone"
    REDIRECT_ENDPOINT_NAME = "study_endpoints.edit_study"
    
    def test_study_admin(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self._test_success()
    
    def test_site_admin(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        self._test_success()
    
    def _test_success(self):
        self.smart_post(self.session_study.id, new_timezone_name="Pacific/Noumea")
        self.session_study.refresh_from_db()
        self.assertEqual(self.session_study.timezone_name, "Pacific/Noumea")
