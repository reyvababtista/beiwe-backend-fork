from constants.message_strings import MFA_RESET_BAD_PERMISSIONS
from constants.user_constants import ResearcherRole
from database.user_models_researcher import Researcher
from tests.common import ResearcherSessionTest


#
## system_admin_pages
#


class TestManageResearchers(ResearcherSessionTest):
    ENDPOINT_NAME = "system_admin_pages.manage_researchers"
    
    def test_researcher(self):
        self.smart_get_status_code(403)
    
    def test_study_admin(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self.smart_get_status_code(200)
    
    def test_site_admin(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        self.smart_get_status_code(200)
    
    def test_render_study_admin(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self._test_render_with_researchers()
        # make sure that site admins are not present
        r4 = self.generate_researcher(relation_to_session_study=ResearcherRole.site_admin)
        resp = self.smart_get_status_code(200)
        self.assert_not_present(r4.username, resp.content)
        
        # make sure that unaffiliated researchers are not present
        r5 = self.generate_researcher()
        resp = self.smart_get_status_code(200)
        self.assert_not_present(r5.username, resp.content)
    
    def test_render_site_admin(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        self._test_render_with_researchers()
        # make sure that site admins ARE present
        r4 = self.generate_researcher(relation_to_session_study=ResearcherRole.site_admin)
        resp = self.smart_get_status_code(200)
        self.assert_present(r4.username, resp.content)
        
        # make sure that unaffiliated researchers ARE present
        r5 = self.generate_researcher()
        resp = self.smart_get_status_code(200)
        self.assert_present(r5.username, resp.content)
    
    def _test_render_with_researchers(self):
        # render the page with a regular user
        r2 = self.generate_researcher(relation_to_session_study=ResearcherRole.researcher)
        resp = self.smart_get_status_code(200)
        self.assert_present(r2.username, resp.content)
        
        # render with 2 reseaorchers
        r3 = self.generate_researcher(relation_to_session_study=ResearcherRole.researcher)
        resp = self.smart_get_status_code(200)
        self.assert_present(r2.username, resp.content)
        self.assert_present(r3.username, resp.content)


class TestResetResearcherMFA(ResearcherSessionTest):
    ENDPOINT_NAME = "system_admin_pages.reset_researcher_mfa"
    REDIRECT_ENDPOINT_NAME = "system_admin_pages.edit_researcher"
    
    def test_reset_as_site_admin(self):
        self._test_reset(self.generate_researcher(), ResearcherRole.site_admin)
    
    def test_reset_as_site_admin_on_site_admin(self):
        researcher = self.generate_researcher()
        self.generate_study_relation(researcher, self.session_study, ResearcherRole.site_admin)
        self._test_reset(researcher, ResearcherRole.site_admin)
    
    def test_reset_as_study_admin_on_good_researcher(self):
        researcher = self.generate_researcher()
        self.generate_study_relation(researcher, self.session_study, ResearcherRole.researcher)
        self._test_reset(researcher, ResearcherRole.study_admin)
    
    def test_reset_as_study_admin_on_bad_researcher(self):
        researcher = self.generate_researcher()
        self._test_reset_fail(researcher, ResearcherRole.study_admin, 403)
    
    def test_reset_as_study_admin_on_site_admin(self):
        researcher = self.generate_researcher()
        self.generate_study_relation(researcher, self.session_study, ResearcherRole.site_admin)
        self._test_reset_fail(researcher, ResearcherRole.study_admin, 403)
    
    def test_reset_study_admin_with_good_study_admin(self):
        researcher = self.generate_researcher()
        self.generate_study_relation(researcher, self.session_study, ResearcherRole.study_admin)
        self._test_reset(researcher, ResearcherRole.study_admin)
    
    def test_no_researcher(self):
        # basically, it should 404
        self.set_session_study_relation(ResearcherRole.site_admin)
        resp = self.smart_post(
            0
        )  # not the magic redirect smart post; 0 will always be an invalid researcher id
        self.assertEqual(404, resp.status_code)
    
    def _test_reset(self, researcher: Researcher, role: ResearcherRole):
        researcher.reset_mfa()
        self.set_session_study_relation(role)
        self.smart_post(researcher.id)  # magic redirect smart post, tests for a redirect
        researcher.refresh_from_db()
        self.assertIsNone(researcher.mfa_token)
        resp = self.easy_get(self.REDIRECT_ENDPOINT_NAME, researcher_pk=researcher.id)
        self.assert_present("MFA token cleared for researcher ", resp.content)
    
    def _test_reset_fail(self, researcher: Researcher, role: ResearcherRole, status_code: int):
        researcher.reset_mfa()
        self.set_session_study_relation(role)
        resp = self.smart_post(
            researcher.id
        )  # not the magic redirect smart post; 0 will always be an invalid researcher id
        self.assertEqual(status_code, resp.status_code)
        researcher.refresh_from_db()
        self.assertIsNotNone(researcher.mfa_token)
        resp = self.easy_get(self.REDIRECT_ENDPOINT_NAME, researcher_pk=researcher.id)
        if resp.status_code == 403:
            self.assert_present(MFA_RESET_BAD_PERMISSIONS, resp.content)


class TestEditResearcher(ResearcherSessionTest):
    ENDPOINT_NAME = "system_admin_pages.edit_researcher"
    
    # render self
    def test_render_for_self_as_researcher(self):
        # should fail
        self.set_session_study_relation()
        self.smart_get_status_code(403, self.session_researcher.id)
    
    def test_render_for_self_as_study_admin(self):
        # ensure it renders (buttons will be disabled)
        self.set_session_study_relation(ResearcherRole.study_admin)
        self.smart_get_status_code(200, self.session_researcher.id)
    
    def test_render_for_self_as_site_admin(self):
        # ensure it renders (buttons will be disabled)
        self.set_session_study_relation(ResearcherRole.site_admin)
        self.smart_get_status_code(200, self.session_researcher.id)
    
    def test_render_for_researcher_as_researcher(self):
        # should fail
        self.set_session_study_relation()
        # set up, test when not on study
        r2 = self.generate_researcher()
        resp = self.smart_get_status_code(403, r2.id)
        self.assert_not_present(r2.username, resp.content)
        # attach other researcher and try again
        self.generate_study_relation(r2, self.session_study, ResearcherRole.researcher)
        resp = self.smart_get_status_code(403, r2.id)
        self.assert_not_present(r2.username, resp.content)
    
    # study admin, renders
    def test_render_valid_researcher_as_study_admin(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self._test_render_generic_under_study()
    
    def test_render_researcher_with_no_study_as_study_admin(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self._test_render_researcher_with_no_study()
    
    # site admin, renders
    def test_render_valid_researcher_as_site_admin(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        self._test_render_generic_under_study()
    
    def test_render_researcher_with_no_study_as_site_admin(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        self._test_render_researcher_with_no_study()
    
    def _test_render_generic_under_study(self):
        r2 = self.generate_researcher(relation_to_session_study=ResearcherRole.researcher)
        resp = self.smart_get_status_code(200, r2.id)
        self.assert_present(r2.username, resp.content)
    
    def _test_render_researcher_with_no_study(self):
        r2 = self.generate_researcher()
        resp = self.smart_get_status_code(200, r2.id)
        self.assert_present(r2.username, resp.content)
