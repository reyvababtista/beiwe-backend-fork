from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.utils import timezone

from config.jinja2 import easy_url
from constants.message_strings import (MFA_CODE_6_DIGITS, MFA_CODE_DIGITS_ONLY, MFA_CODE_MISSING,
    MFA_SELF_BAD_PASSWORD, MFA_SELF_DISABLED, MFA_SELF_NO_PASSWORD, MFA_SELF_SUCCESS,
    MFA_TEST_DISABLED, MFA_TEST_FAIL, MFA_TEST_SUCCESS, NEW_PASSWORD_MISMATCH, NEW_PASSWORD_N_LONG,
    NEW_PASSWORD_RULES_FAIL, PASSWORD_RESET_SUCCESS, WRONG_CURRENT_PASSWORD)
from constants.security_constants import MFA_CREATED
from constants.user_constants import ResearcherRole
from database.security_models import ApiKey
from tests.common import ResearcherSessionTest


#
## admin_pages
#


class TestViewStudy(ResearcherSessionTest):
    """ view_study is pretty simple, no custom content in the :
    tests push_notifications_enabled, study.forest_enabled
    populates html elements with custom field values
    populates html elements of survey buttons """
    
    ENDPOINT_NAME = "admin_pages.view_study"
    
    def test_view_study_no_relation(self):
        self.smart_get_status_code(403, self.session_study.id)
    
    def test_view_study_researcher(self):
        # pretty much just tests that the page loads, removing is_test removed template customizations.
        study = self.session_study
        self.set_session_study_relation(ResearcherRole.researcher)
        self.smart_get_status_code(200, study.id)
    
    def test_view_study_study_admin(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self.smart_get_status_code(200, self.session_study.id)
    
    @patch('pages.admin_pages.check_firebase_instance')
    def test_view_study_site_admin(self, check_firebase_instance: MagicMock):
        study = self.session_study
        self.set_session_study_relation(ResearcherRole.site_admin)
        
        # test rendering with several specifc values set to observe the rendering changes
        study.update(forest_enabled=False)
        check_firebase_instance.return_value = False
        response = self.smart_get_status_code(200, study.id)
        self.assertNotIn(
            b"Configure Interventions for use with Relative survey schedules", response.content
        )
        self.assertNotIn(b"View Forest Task Log", response.content)
        
        check_firebase_instance.return_value = True
        study.update(forest_enabled=True)
        response = self.smart_get_status_code(200, study.id)
        self.assertIn(
            b"Configure Interventions for use with Relative survey schedules", response.content
        )
        self.assertIn(b"View Forest Task Log", response.content)
        # assertInHTML is several hundred times slower but has much better output when it fails...
        # self.assertInHTML("Configure Interventions for use with Relative survey schedules", response.content.decode())


class TestManageCredentials(ResearcherSessionTest):
    ENDPOINT_NAME = "admin_pages.manage_credentials"
    
    def test_manage_credentials(self):
        self.session_study
        self.smart_get_status_code(200)
        api_key = ApiKey.generate(
            researcher=self.session_researcher,
            has_tableau_api_permissions=True,
            readable_name="not important",
        )
        response = self.smart_get_status_code(200)
        self.assert_present(api_key.access_key_id, response.content)
    
    def test_mfa_not_visible(self):
        # qr code should only be visible if mfa password was provided (and matches) and session does
        # not contain the MFA_CREATED key
        session = self.client.session  # this creates a new object
        self.session_researcher.reset_mfa()
        # use the alt text to test for presence of the qr code
        self.assert_not_present('alt="MFA QR Code"', self.smart_get_status_code(200).content)
        session[MFA_CREATED] = timezone.now() - timedelta(seconds=60)
        session.save()
        self.assert_not_present('alt="MFA QR Code"', self.smart_get_status_code(200).content)
    
    def test_mfa_visible_session_manip(self):
        session = self.client.session  # this creates a new object
        self.session_researcher.reset_mfa()
        session[MFA_CREATED] = timezone.now()
        session.save()  # save the session because this isn't inside the request/response cycle
        self.assert_present('alt="MFA QR Code"', self.smart_get_status_code(200).content)
    
    def test_mfa_visible_password(self):
        self.session_researcher.reset_mfa()
        resp = self.smart_post_status_code(200, view_mfa_password=self.DEFAULT_RESEARCHER_PASSWORD)
        self.assert_present('alt="MFA QR Code"', resp.content)


class TestResetAdminPassword(ResearcherSessionTest):
    # test for every case and messages present on the page
    ENDPOINT_NAME = "admin_pages.reset_admin_password"
    REDIRECT_ENDPOINT_NAME = "admin_pages.manage_credentials"
    
    def test_reset_admin_password_success(self):
        resp = self.smart_post_status_code(
            302,
            current_password=self.DEFAULT_RESEARCHER_PASSWORD,
            new_password=self.DEFAULT_RESEARCHER_PASSWORD + "1",
            confirm_new_password=self.DEFAULT_RESEARCHER_PASSWORD + "1",
        )
        # the initial redirect is to the normal endpoint
        self.assertEqual(resp.url, easy_url(self.REDIRECT_ENDPOINT_NAME))
        
        r = self.session_researcher
        r.refresh_from_db()
        self.assertFalse(r.check_password(r.username, self.DEFAULT_RESEARCHER_PASSWORD))
        self.assertTrue(r.check_password(r.username, self.DEFAULT_RESEARCHER_PASSWORD + "1"))
        r.force_global_logout()
        self.assertEqual(self.session_researcher.web_sessions.count(), 0)
        resp = self.easy_get(self.REDIRECT_ENDPOINT_NAME, 302)
        self.assertEqual(resp.url, easy_url("login_pages.login_page"))
        resp = self.easy_get("login_pages.login_page", 200)
        self.assert_present(PASSWORD_RESET_SUCCESS, resp.content)
    
    def test_reset_admin_password_wrong(self):
        self.smart_post(
            current_password=self.DEFAULT_RESEARCHER_PASSWORD + "1",
            new_password=self.DEFAULT_RESEARCHER_PASSWORD + "1",
            confirm_new_password=self.DEFAULT_RESEARCHER_PASSWORD + "1",
        )
        r = self.session_researcher
        self.assertTrue(r.check_password(r.username, self.DEFAULT_RESEARCHER_PASSWORD))
        self.assertFalse(r.check_password(r.username, self.DEFAULT_RESEARCHER_PASSWORD + "1"))
        self.assert_present(WRONG_CURRENT_PASSWORD, self.redirect_get_contents())
    
    def test_reset_admin_password_rules_fail(self):
        non_default = "abcdefghijklmnop"
        self.smart_post(
            current_password=self.DEFAULT_RESEARCHER_PASSWORD,
            new_password=non_default,
            confirm_new_password=non_default,
        )
        r = self.session_researcher
        self.assertTrue(r.check_password(r.username, self.DEFAULT_RESEARCHER_PASSWORD))
        self.assertFalse(r.check_password(r.username, non_default))
        self.assert_present(NEW_PASSWORD_RULES_FAIL, self.redirect_get_contents())
    
    def test_reset_admin_password_too_short(self):
        non_default = "a1#"
        self.smart_post(
            current_password=self.DEFAULT_RESEARCHER_PASSWORD,
            new_password=non_default,
            confirm_new_password=non_default,
        )
        r = self.session_researcher
        self.assertTrue(r.check_password(r.username, self.DEFAULT_RESEARCHER_PASSWORD))
        self.assertFalse(r.check_password(r.username, non_default))
        self.assert_present(NEW_PASSWORD_N_LONG.format(length=8), self.redirect_get_contents())
    
    def test_reset_admin_password_too_short_study_setting(self):
        self.session_study.update(password_minimum_length=20)
        self.set_session_study_relation(ResearcherRole.researcher)
        non_default = "aA1#aA1#aA1#aA1#"  # 10 chars
        self.smart_post(
            current_password=self.DEFAULT_RESEARCHER_PASSWORD,
            new_password=non_default,
            confirm_new_password=non_default,
        )
        r = self.session_researcher
        self.assertTrue(r.check_password(r.username, self.DEFAULT_RESEARCHER_PASSWORD))
        self.assertFalse(r.check_password(r.username, non_default))
        self.assert_present(NEW_PASSWORD_N_LONG.format(length=20), self.redirect_get_contents())
    
    def test_reset_admin_password_too_short_site_admin(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        non_default = "aA1#aA1#aA1#aA1#"  # 10 chars
        self.smart_post(
            current_password=self.DEFAULT_RESEARCHER_PASSWORD,
            new_password=non_default,
            confirm_new_password=non_default,
        )
        r = self.session_researcher
        self.assertTrue(r.check_password(r.username, self.DEFAULT_RESEARCHER_PASSWORD))
        self.assertFalse(r.check_password(r.username, non_default))
        self.assert_present(NEW_PASSWORD_N_LONG.format(length=20), self.redirect_get_contents())
    
    def test_reset_admin_password_mismatch(self):
        # has to pass the length and character checks
        self.smart_post(
            current_password=self.DEFAULT_RESEARCHER_PASSWORD,
            new_password="aA1#aA1#aA1#",
            confirm_new_password="aA1#aA1#aA1#aA1#",
        )
        researcher = self.session_researcher
        self.assertTrue(
            researcher.check_password(researcher.username, self.DEFAULT_RESEARCHER_PASSWORD)
        )
        self.assertFalse(researcher.check_password(researcher.username, "aA1#aA1#aA1#"))
        self.assertFalse(researcher.check_password(researcher.username, "aA1#aA1#aA1#aA1#"))
        self.assert_present(NEW_PASSWORD_MISMATCH, self.redirect_get_contents())


class TestResetDownloadApiCredentials(ResearcherSessionTest):
    ENDPOINT_NAME = "admin_pages.reset_download_api_credentials"
    REDIRECT_ENDPOINT_NAME = "admin_pages.manage_credentials"
    
    def test_reset(self):
        self.assertIsNone(self.session_researcher.access_key_id)
        self.smart_post()
        self.session_researcher.refresh_from_db()
        self.assertIsNotNone(self.session_researcher.access_key_id)
        self.assert_present(
            "Your Data-Download API access credentials have been reset",
            self.redirect_get_contents()
        )


class TestResetMFASelf(ResearcherSessionTest):
    ENDPOINT_NAME = "admin_pages.reset_mfa_self"
    REDIRECT_ENDPOINT_NAME = "admin_pages.manage_credentials"
    
    def test_no_password(self):
        session = self.client.session
        orig_mfa = self.session_researcher.reset_mfa()
        self.smart_post()  # magic redirect smart post, tests for the redirect
        resp = self.easy_get(self.REDIRECT_ENDPOINT_NAME)
        self.assert_present(MFA_SELF_NO_PASSWORD, resp.content)
        self.session_researcher.refresh_from_db()
        self.assertIsNotNone(self.session_researcher.mfa_token)
        self.assertEqual(orig_mfa, self.session_researcher.mfa_token)  # no change
        self.assertNotIn(MFA_CREATED, session)
    
    def test_bad_password(self):
        session = self.client.session
        orig_mfa = self.session_researcher.reset_mfa()
        self.smart_post(mfa_password="wrong_password")  # magic redirect smart post
        resp = self.easy_get(self.REDIRECT_ENDPOINT_NAME)
        self.assert_present(MFA_SELF_BAD_PASSWORD, resp.content)
        self.assertIsNotNone(self.session_researcher.mfa_token)
        self.assertEqual(orig_mfa, self.session_researcher.mfa_token)  # no change
        self.assertNotIn(MFA_CREATED, session)
    
    def test_mfa_reset_with_mfa_token(self):
        # case is not accessible from webpage
        session = self.client.session
        orig_mfa = self.session_researcher.reset_mfa()
        self.smart_post(mfa_password=self.DEFAULT_RESEARCHER_PASSWORD)  # magic redirect smart post
        resp = self.easy_get(self.REDIRECT_ENDPOINT_NAME)
        self.assert_present(MFA_SELF_SUCCESS, resp.content)
        self.session_researcher.refresh_from_db()
        self.assertIsNotNone(self.session_researcher.mfa_token)
        self.assertNotEqual(orig_mfa, self.session_researcher.mfa_token)  # change!
        self.assertIn(MFA_CREATED, session)
    
    def test_mfa_reset_without_mfa_token(self):
        session = self.client.session
        self.smart_post(mfa_password=self.DEFAULT_RESEARCHER_PASSWORD)  # magic redirect smart post
        resp = self.easy_get(self.REDIRECT_ENDPOINT_NAME)
        self.assert_present(MFA_SELF_SUCCESS, resp.content)
        self.session_researcher.refresh_from_db()
        self.assertIsNotNone(self.session_researcher.mfa_token)  # change!
        self.assertIn(MFA_CREATED, session)
    
    def test_mfa_clear_with_token(self):
        session = self.client.session
        orig_mfa = self.session_researcher.reset_mfa()
        # disable can be any non-falsy value
        self.smart_post(mfa_password=self.DEFAULT_RESEARCHER_PASSWORD, disable="true")
        resp = self.easy_get(self.REDIRECT_ENDPOINT_NAME)
        self.assert_present(MFA_SELF_DISABLED, resp.content)
        self.session_researcher.refresh_from_db()
        self.assertIsNone(self.session_researcher.mfa_token)
        self.assertNotEqual(orig_mfa, self.session_researcher.mfa_token)  # change!
        self.assertNotIn(MFA_CREATED, session)
    
    def test_mfa_clear_without_mfa_token(self):
        session = self.client.session
        # disable can be any non-falsy value
        self.smart_post(mfa_password=self.DEFAULT_RESEARCHER_PASSWORD, disable="true")
        resp = self.easy_get(self.REDIRECT_ENDPOINT_NAME)
        self.assert_present(MFA_SELF_DISABLED, resp.content)
        self.session_researcher.refresh_from_db()
        self.assertIsNone(self.session_researcher.mfa_token)  # change!
        self.assertNotIn(MFA_CREATED, session)


class TestTestMFA(ResearcherSessionTest):
    ENDPOINT_NAME = "admin_pages.test_mfa"
    REDIRECT_ENDPOINT_NAME = "admin_pages.manage_credentials"
    
    def test_mfa_working_fails(self):
        self.session_researcher.reset_mfa()  # enable mfa
        if self.session_researcher._mfa_now == "123456":
            self.session_researcher.reset_mfa()  # ensure mfa code is not 123456
        
        self.smart_post()  # magic redirect smart post
        page = self.simple_get(easy_url("admin_pages.manage_credentials"), status_code=200).content
        self.assert_present(MFA_CODE_MISSING, page)  # missing mfa code
        
        self.smart_post(mfa_code="123456")  # wrong mfa code
        page = self.simple_get(easy_url("admin_pages.manage_credentials"), status_code=200).content
        self.assert_present(MFA_TEST_FAIL, page)
        
        self.smart_post(mfa_code="1234567")  # too long mfa code
        page = self.simple_get(easy_url("admin_pages.manage_credentials"), status_code=200).content
        self.assert_present(MFA_CODE_6_DIGITS, page)
        
        self.smart_post(mfa_code="abcdef")  # non-numeric mfa code
        page = self.simple_get(easy_url("admin_pages.manage_credentials"), status_code=200).content
        self.assert_present(MFA_CODE_DIGITS_ONLY, page)
        
        self.smart_post(mfa_code=self.session_researcher._mfa_now)  # correct mfa code
        page = self.simple_get(easy_url("admin_pages.manage_credentials"), status_code=200).content
        self.assert_present(MFA_TEST_SUCCESS, page)
        
        self.session_researcher.clear_mfa()  # disabled mfa
        self.smart_post(mfa_code="abcdef")
        page = self.simple_get(easy_url("admin_pages.manage_credentials"), status_code=200).content
        self.assert_present(MFA_TEST_DISABLED, page)


class TestElevateResearcher(ResearcherSessionTest):
    ENDPOINT_NAME = "system_admin_pages.elevate_researcher"
    
    # (this one is tedious.)
    
    def test_self_as_researcher_on_study(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.smart_post_status_code(
            403, researcher_id=self.session_researcher.id, study_id=self.session_study.id
        )
    
    def test_self_as_study_admin_on_study(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self.smart_post_status_code(
            403, researcher_id=self.session_researcher.id, study_id=self.session_study.id
        )
    
    def test_researcher_as_study_admin_on_study(self):
        # this is the only case that succeeds
        self.set_session_study_relation(ResearcherRole.study_admin)
        r2 = self.generate_researcher(relation_to_session_study=ResearcherRole.researcher)
        self.smart_post_status_code(302, researcher_id=r2.id, study_id=self.session_study.id)
        self.assertEqual(r2.study_relations.get().relationship, ResearcherRole.study_admin)
    
    def test_study_admin_as_study_admin_on_study(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        r2 = self.generate_researcher(relation_to_session_study=ResearcherRole.study_admin)
        self.smart_post_status_code(403, researcher_id=r2.id, study_id=self.session_study.id)
        self.assertEqual(r2.study_relations.get().relationship, ResearcherRole.study_admin)
    
    def test_site_admin_as_study_admin_on_study(self):
        self.session_researcher
        self.set_session_study_relation(ResearcherRole.study_admin)
        r2 = self.generate_researcher(relation_to_session_study=ResearcherRole.site_admin)
        self.smart_post_status_code(403, researcher_id=r2.id, study_id=self.session_study.id)
        self.assertFalse(r2.study_relations.filter(study=self.session_study).exists())
    
    def test_site_admin_as_site_admin(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        r2 = self.generate_researcher(relation_to_session_study=ResearcherRole.site_admin)
        self.smart_post_status_code(403, researcher_id=r2.id, study_id=self.session_study.id)
        self.assertFalse(r2.study_relations.filter(study=self.session_study).exists())
