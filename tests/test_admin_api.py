from django.http.response import HttpResponseRedirect

from constants.message_strings import PASSWORD_RESET_FAIL_SITE_ADMIN
from constants.user_constants import ResearcherRole
from database.profiling_models import DataAccessRecord
from database.security_models import ApiKey
from database.study_models import Study
from database.user_models_researcher import Researcher, StudyRelation
from tests.common import ResearcherSessionTest


#
## admin_api
#
class TestRemoveResearcherFromStudy(ResearcherSessionTest):
    ENDPOINT_NAME = "admin_api.remove_researcher_from_study"
    REDIRECT_ENDPOINT_NAME = "system_admin_pages.edit_study"
    
    def test_site_admin(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        self._test(None, 302)
        self._test(ResearcherRole.study_admin, 302)
        self._test(ResearcherRole.researcher, 302)
        self._test(ResearcherRole.site_admin, 302)
    
    def test_study_admin(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self._test(None, 403)
        self._test(ResearcherRole.study_admin, 403)
        self._test(ResearcherRole.researcher, 302)
        self._test(ResearcherRole.site_admin, 403)
    
    def test_researcher(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        r2 = self.generate_researcher(relation_to_session_study=None)
        self.smart_post_status_code(
            403,
            study_id=self.session_study.id,
            researcher_id=r2.id,
            redirect_url=f"/edit_study/{self.session_study.id}"
        )
    
    def _test(self, r2_starting_relation, status_code):
        if r2_starting_relation == ResearcherRole.site_admin:
            r2 = self.generate_researcher(relation_to_session_study=ResearcherRole.site_admin)
        else:
            r2 = self.generate_researcher(relation_to_session_study=r2_starting_relation)
        redirect = self.smart_post(
            study_id=self.session_study.id,
            researcher_id=r2.id,
            redirect_url=f"/edit_study/{self.session_study.id}"
        )
        # needs to be a None at the end
        self.assertEqual(redirect.status_code, status_code)
        if isinstance(redirect, HttpResponseRedirect):
            self.assert_researcher_relation(r2, self.session_study, None)
            self.assertEqual(redirect.url, f"/edit_study/{self.session_study.id}")


class TestDeleteResearcher(ResearcherSessionTest):
    ENDPOINT_NAME = "admin_api.delete_researcher"
    
    def test_site_admin(self):
        self._test_basics(302, ResearcherRole.site_admin, True)
    
    def test_study_admin(self):
        self._test_basics(403, ResearcherRole.study_admin, False)
    
    def test_researcher(self):
        self._test_basics(403, ResearcherRole.researcher, False)
    
    def test_no_relation(self):
        self._test_basics(403, None, False)
    
    def test_nonexistent(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        # 0 is not a valid database key.
        self.smart_get_status_code(404, 0)
    
    def _test_basics(self, status_code: int, relation: str, success: bool):
        self.set_session_study_relation(relation)  # implicitly creates self.session_researcher
        r2 = self.generate_researcher()
        self.smart_get_status_code(status_code, r2.id)
        self.assertEqual(Researcher.objects.filter(id=r2.id).count(), 0 if success else 1)
    
    def test_cascade(self):
        # first assert that this is actually all the relations:
        self.assertEqual(
            [obj.related_model.__name__ for obj in Researcher._meta.related_objects],
            ['StudyRelation', 'ResearcherSession', 'DataAccessRecord', 'ApiKey']
        )
        # we need the test to succeed...
        self.set_session_study_relation(ResearcherRole.site_admin)
        r2 = self.generate_researcher()
        
        # generate all possible researcher relations for r2 as determined above:
        ApiKey.generate(
            researcher=r2, has_tableau_api_permissions=True, readable_name="test_api_key"
        )
        relation_id = self.generate_study_relation(
            r2, self.default_study, ResearcherRole.researcher
        ).id
        record = DataAccessRecord.objects.create(
            researcher=r2, query_params="test_junk", username=r2.username
        )
        # for tests after deletion
        relation_id = r2.study_relations.get().id
        default_study_id = self.default_study.id
        # request
        self.smart_get_status_code(302, r2.id)
        # test that these were deleted
        self.assertFalse(Researcher.objects.filter(id=r2.id).exists())
        self.assertFalse(ApiKey.objects.exists())
        self.assertFalse(StudyRelation.objects.filter(id=relation_id).exists())
        # I can never remember the direction of cascade, confirm study is still there
        self.assertTrue(Study.objects.filter(id=default_study_id).exists())
        # and assert that the DataAccessRecord is still there with a null researcher and a username.
        self.assertTrue(DataAccessRecord.objects.filter(id=record.id).exists())
        record.refresh_from_db()
        self.assertIsNone(record.researcher)
        self.assertEqual(record.username, r2.username)


class TestSetResearcherPassword(ResearcherSessionTest):
    ENDPOINT_NAME = "admin_api.set_researcher_password"
    
    def test_site_admin_on_a_null_user(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        r2 = self.generate_researcher()
        self._test_successful_change(r2)
    
    def test_site_admin_on_researcher(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        r2 = self.generate_researcher()
        self.generate_study_relation(r2, self.default_study, ResearcherRole.researcher)
        self._test_successful_change(r2)
    
    def test_site_admin_on_study_admin(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        r2 = self.generate_researcher()
        self.generate_study_relation(r2, self.default_study, ResearcherRole.study_admin)
        self._test_successful_change(r2)
    
    def test_site_admin_on_site_admin(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        r2 = self.generate_researcher()
        self.generate_study_relation(r2, self.default_study, ResearcherRole.site_admin)
        self._test_cannot_change(r2, PASSWORD_RESET_FAIL_SITE_ADMIN)
    
    def _test_successful_change(self, r2: Researcher):
        self.smart_post(
            researcher_id=r2.id,
            password=self.DEFAULT_RESEARCHER_PASSWORD + "1",
        )
        # we are ... teleologically correct here mimicking the code...
        r2.refresh_from_db()
        self.assertTrue(r2.password_force_reset)
        self.assertTrue(r2.check_password(r2.username, self.DEFAULT_RESEARCHER_PASSWORD + "1"))
        self.assertFalse(r2.check_password(r2.username, self.DEFAULT_RESEARCHER_PASSWORD))
        self.assertEqual(r2.web_sessions.count(), 0)
    
    def _test_cannot_change(self, r2: Researcher, message: str = None):
        ret = self.smart_post(
            researcher_id=r2.id,
            password=self.DEFAULT_RESEARCHER_PASSWORD + "1",
        )
        if message:
            content = self.easy_get(
                "system_admin_pages.edit_researcher", researcher_pk=r2.id
            ).content
            self.assert_present(message, content)
        r2.refresh_from_db()
        self.assertFalse(r2.password_force_reset)
        self.assertFalse(r2.check_password(r2.username, self.DEFAULT_RESEARCHER_PASSWORD + "1"))
        self.assertTrue(r2.check_password(r2.username, self.DEFAULT_RESEARCHER_PASSWORD))
        self.assertEqual(self.session_researcher.web_sessions.count(), 1)
        return ret


class TestToggleStudyEasyEnrollment(ResearcherSessionTest):
    ENDPOINT_NAME = "admin_api.toggle_easy_enrollment_study"
    REDIRECT_ENDPOINT_NAME = "system_admin_pages.edit_study"
    
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
    ENDPOINT_NAME = "admin_api.rename_study"
    REDIRECT_ENDPOINT_NAME = "system_admin_pages.edit_study"
    
    def test(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        self.smart_post_redirect(self.session_study.id, new_study_name="hello!")
        self.session_study.refresh_from_db()
        self.assertEqual(self.session_study.name, "hello!")


class TestPrivacyPolicy(ResearcherSessionTest):
    ENDPOINT_NAME = "admin_api.download_privacy_policy"
    
    def test(self):
        # just test that it loads without breaking
        redirect = self.smart_get()
        self.assertIsInstance(redirect, HttpResponseRedirect)
