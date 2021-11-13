from copy import copy
from typing import List
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import models
from django.forms.fields import NullBooleanField
from django.http.response import HttpResponseRedirect
from django.urls import reverse

from config.jinja2 import easy_url
from constants.celery_constants import (ANDROID_FIREBASE_CREDENTIALS, BACKEND_FIREBASE_CREDENTIALS,
    IOS_FIREBASE_CREDENTIALS)
from constants.data_stream_constants import ALL_DATA_STREAMS
from constants.message_strings import (NEW_PASSWORD_8_LONG, NEW_PASSWORD_MISMATCH,
    NEW_PASSWORD_RULES_FAIL, PASSWORD_RESET_SUCCESS, TABLEAU_API_KEY_IS_DISABLED,
    TABLEAU_NO_MATCHING_API_KEY, WRONG_CURRENT_PASSWORD)
from constants.researcher_constants import ALL_RESEARCHER_TYPES, ResearcherRole
from constants.testing_constants import (ADMIN_ROLES, ALL_TESTING_ROLES, ANDROID_CERT, BACKEND_CERT,
    IOS_CERT)
from database.security_models import ApiKey
from database.study_models import DeviceSettings, Study
from database.system_models import FileAsText
from database.user_models import Researcher
from libs.security import generate_easy_alphanumeric_string
from tests.common import (BasicSessionTestCase, GeneralPageTest, PopulatedSessionTestCase,
    RedirectSessionApiTest, SessionApiTest)


class TestLoginPages(BasicSessionTestCase):
    """ Basic authentication test, make sure that the machinery for logging a user
    in and out are functional at setting and clearing a session. """
    
    def test_load_login_page_while_not_logged_in(self):
        # make sure the login page loads without logging you in when it should not
        response = self.client.post(reverse("login_pages.login_page"))
        self.assertEqual(response.status_code, 200)
        # this should uniquely identify the login page
        self.assertIn(b'<form method="POST" action="/validate_login">', response.content)
    
    def test_load_login_page_while_logged_in(self):
        # make sure the login page loads without logging you in when it should not
        self.session_researcher  # create the default researcher
        self.do_default_login()
        response = self.client.post(reverse("login_pages.login_page"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin_pages.choose_study"))
        # this should uniquely identify the login page
        self.assertNotIn(b'<form method="POST" action="/validate_login">', response.content)
    
    def test_logging_in_success(self):
        self.session_researcher  # create the default researcher
        r = self.do_default_login()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("admin_pages.choose_study"))
    
    def test_logging_in_fail(self):
        r = self.do_default_login()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("login_pages.login_page"))
    
    def test_logging_out(self):
        # create the default researcher, login, logout, attempt going to main page,
        self.session_researcher
        self.do_default_login()
        self.client.get(reverse("admin_pages.logout_admin"))
        r = self.client.get(reverse("admin_pages.choose_study"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, reverse("login_pages.login_page"))


class TestViewStudy(GeneralPageTest):
    """ view_study is pretty simple, no custom content in the :
    tests push_notifications_enabled, is_site_admin, study.is_test, study.forest_enabled
    populates html elements with custom field values
    populates html elements of survey buttons
    """
    
    ENDPOINT_NAME = "admin_pages.view_study"
    
    def test_view_study_no_relation(self):
        self.do_test_status_code(403, self.session_study.id)
    
    def test_view_study_researcher(self):
        study = self.session_study
        study.update(is_test=True)
        self.set_session_study_relation(ResearcherRole.researcher)
        response = self.do_test_status_code(200, study.id)
        
        # template has several customizations, test for some relevant strings
        self.assertIn(b"This is a test study.", response.content)
        self.assertNotIn(b"This is a production study", response.content)
        study.update(is_test=False)
        
        response = self.do_test_status_code(200, study.id)
        self.assertNotIn(b"This is a test study.", response.content)
        self.assertIn(b"This is a production study", response.content)
    
    def test_view_study_study_admin(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self.do_test_status_code(200, self.session_study.id)
    
    @patch('pages.admin_pages.check_firebase_instance')
    def test_view_study_site_admin(self, check_firebase_instance: MagicMock):
        study = self.session_study
        self.session_researcher.update(site_admin=True)
        
        # test rendering with several specifc values set to observe the rendering changes
        study.update(forest_enabled=False)
        check_firebase_instance.return_value = False
        response = self.do_test_status_code(200, study.id)
        self.assertNotIn(b"Edit interventions for this study", response.content)
        self.assertNotIn(b"View Forest Task Log", response.content)
        
        check_firebase_instance.return_value = True
        study.update(forest_enabled=True)
        response = self.do_test_status_code(200, study.id)
        self.assertIn(b"Edit interventions for this study", response.content)
        self.assertIn(b"View Forest Task Log", response.content)
        # assertInHTML is several hundred times slower but has much better output when it fails...
        # self.assertInHTML("Edit interventions for this study", response.content.decode())


class TestManageCredentials(GeneralPageTest):
    ENDPOINT_NAME = "admin_pages.manage_credentials"
    
    def test_manage_credentials(self):
        self.session_study
        self.do_test_status_code(200)
        api_key = ApiKey.generate(
            researcher=self.session_researcher,
            has_tableau_api_permissions=True,
            readable_name="not important",
        )
        response = self.do_test_status_code(200)
        self.assert_present(api_key.access_key_id, response.content)


class TestResetAdminPassword(RedirectSessionApiTest):
    # test for every case and messages present on the page
    ENDPOINT_NAME = "admin_pages.reset_admin_password"
    REDIRECT_ENDPOINT_NAME = "admin_pages.manage_credentials"
    
    def test_reset_admin_password_success(self):
        self.smart_post(
            current_password=self.DEFAULT_RESEARCHER_PASSWORD,
            new_password=self.DEFAULT_RESEARCHER_PASSWORD + "1",
            confirm_new_password=self.DEFAULT_RESEARCHER_PASSWORD + "1",
        )
        # we are ... teleologically correct here mimicking the code...
        researcher = self.session_researcher
        self.assertFalse(researcher.check_password(researcher.username, self.DEFAULT_RESEARCHER_PASSWORD))
        self.assertTrue(researcher.check_password(researcher.username, self.DEFAULT_RESEARCHER_PASSWORD + "1"))
        # Always stick the check for the string after the check for the db mutation.
        self.assert_present(PASSWORD_RESET_SUCCESS, self.get_redirect_content())
    
    def test_reset_admin_password_wrong(self):
        self.smart_post(
            current_password=self.DEFAULT_RESEARCHER_PASSWORD + "1",
            new_password=self.DEFAULT_RESEARCHER_PASSWORD + "1",
            confirm_new_password=self.DEFAULT_RESEARCHER_PASSWORD + "1",
        )
        researcher = self.session_researcher
        self.assertTrue(researcher.check_password(researcher.username, self.DEFAULT_RESEARCHER_PASSWORD))
        self.assertFalse(researcher.check_password(researcher.username, self.DEFAULT_RESEARCHER_PASSWORD + "1"))
        self.assert_present(WRONG_CURRENT_PASSWORD, self.get_redirect_content())
    
    def test_reset_admin_password_rules_fail(self):
        non_default = "abcdefghijklmnop"
        self.smart_post(
            current_password=self.DEFAULT_RESEARCHER_PASSWORD,
            new_password=non_default,
            confirm_new_password=non_default,
        )
        researcher = self.session_researcher
        self.assertTrue(researcher.check_password(researcher.username, self.DEFAULT_RESEARCHER_PASSWORD))
        self.assertFalse(researcher.check_password(researcher.username, non_default))
        self.assert_present(NEW_PASSWORD_RULES_FAIL, self.get_redirect_content())
    
    def test_reset_admin_password_too_short(self):
        non_default = "a1#"
        self.smart_post(
            current_password=self.DEFAULT_RESEARCHER_PASSWORD,
            new_password=non_default,
            confirm_new_password=non_default,
        )
        researcher = self.session_researcher
        self.assertTrue(researcher.check_password(researcher.username, self.DEFAULT_RESEARCHER_PASSWORD))
        self.assertFalse(researcher.check_password(researcher.username, non_default))
        self.assert_present(NEW_PASSWORD_8_LONG, self.get_redirect_content())
    
    def test_reset_admin_password_mismatch(self):
        # has to pass the length and character checks
        self.smart_post(
            current_password=self.DEFAULT_RESEARCHER_PASSWORD,
            new_password="aA1#aA1#aA1#",
            confirm_new_password="aA1#aA1#aA1#aA1#",
        )
        researcher = self.session_researcher
        self.assertTrue(researcher.check_password(researcher.username, self.DEFAULT_RESEARCHER_PASSWORD))
        self.assertFalse(researcher.check_password(researcher.username, "aA1#aA1#aA1#"))
        self.assertFalse(researcher.check_password(researcher.username, "aA1#aA1#aA1#aA1#"))
        self.assert_present(NEW_PASSWORD_MISMATCH, self.get_redirect_content())


class TestResetDownloadApiCredentials(RedirectSessionApiTest):
    ENDPOINT_NAME = "admin_pages.reset_download_api_credentials"
    REDIRECT_ENDPOINT_NAME = "admin_pages.manage_credentials"
    
    def test_reset(self):
        self.assertIsNone(self.session_researcher.access_key_id)
        self.smart_post()
        self.session_researcher.refresh_from_db()
        self.assertIsNotNone(self.session_researcher.access_key_id)
        self.assert_present("Your Data-Download API access credentials have been reset",
                             self.get_redirect_content())


class TestNewTableauApiKey(RedirectSessionApiTest):
    ENDPOINT_NAME = "admin_pages.new_tableau_api_key"
    REDIRECT_ENDPOINT_NAME = "admin_pages.manage_credentials"
    
    # FIXME: when NewApiKeyForm does anything develop a test for naming the key, probably more.
    #  (need to review the tableau tests)
    def test_reset(self):
        self.assertIsNone(self.session_researcher.api_keys.first())
        self.smart_post()
        self.assertIsNotNone(self.session_researcher.api_keys.first())
        self.assert_present("New Tableau API credentials have been generated for you",
                             self.get_redirect_content())


# admin_pages.disable_tableau_api_key
class TestDisableTableauApiKey(RedirectSessionApiTest):
    ENDPOINT_NAME = "admin_pages.disable_tableau_api_key"
    REDIRECT_ENDPOINT_NAME = "admin_pages.manage_credentials"
    
    def test_disable_success(self):
        # basic test
        api_key = ApiKey.generate(
            researcher=self.session_researcher,
            has_tableau_api_permissions=True,
            readable_name="something",
        )
        self.smart_post(api_key_id=api_key.access_key_id)
        self.assertFalse(self.session_researcher.api_keys.first().is_active)
        content = self.get_redirect_content()
        self.assert_present(api_key.access_key_id, content)
        self.assert_present("is now disabled", content)
    
    def test_no_match(self):
        # fail with empty and fail with success
        self.smart_post(api_key_id="abc")
        self.assert_present(TABLEAU_NO_MATCHING_API_KEY, self.get_redirect_content())
        api_key = ApiKey.generate(
            researcher=self.session_researcher,
            has_tableau_api_permissions=True,
            readable_name="something",
        )
        self.smart_post(api_key_id="abc")
        api_key.refresh_from_db()
        self.assertTrue(api_key.is_active)
        self.assert_present(TABLEAU_NO_MATCHING_API_KEY, self.get_redirect_content())
    
    def test_already_disabled(self):
        api_key = ApiKey.generate(
            researcher=self.session_researcher,
            has_tableau_api_permissions=True,
            readable_name="something",
        )
        api_key.update(is_active=False)
        self.smart_post(api_key_id=api_key.access_key_id)
        api_key.refresh_from_db()
        self.assertFalse(api_key.is_active)
        self.assert_present(TABLEAU_API_KEY_IS_DISABLED, self.get_redirect_content())


class TestDashboard(GeneralPageTest):
    ENDPOINT_NAME = "dashboard_api.dashboard_page"
    
    def test_dashboard(self):
        # default user and default study already instantiated
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.do_test_status_code(200, str(self.session_study.id))
        self.assert_present("Choose a participant or data stream to view", resp.content)


# FIXME: dashboard is going to require a fixture to populate data.
class TestDashboardStream(PopulatedSessionTestCase):
    # this  url doesn't fit any helpers I've built yet
    # dashboard_api.get_data_for_dashboard_datastream_display
    def test_data_streams(self):
        # test is currently limited to rendering the page for each data stream but with no data in it
        self.set_session_study_relation()
        for data_stream in ALL_DATA_STREAMS:
            url = reverse(
                "dashboard_api.get_data_for_dashboard_datastream_display",
                kwargs=dict(study_id=self.session_study.id, data_stream=data_stream),
            )
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 200)
    
    # dashboard_api.dashboard_participant_page
    def test_patient_display(self):
        # this page renders with almost no data
        self.session_researcher
        self.set_session_study_relation()
        url = reverse(
            "dashboard_api.dashboard_participant_page",
            kwargs=dict(study_id=self.session_study.id, patient_id=self.default_participant().patient_id),
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)


# system_admin_pages.manage_researchers
class TestManageResearchers(GeneralPageTest):
    ENDPOINT_NAME = "system_admin_pages.manage_researchers"
    
    def test_researcher(self):
        self.do_test_status_code(403)
    
    def test_study_admin(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self.do_test_status_code(200)
    
    def test_site_admin(self):
        self.session_researcher.update(site_admin=True)
        self.do_test_status_code(200)
    
    def test_render_study_admin(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self._test_render_with_researchers()
        # make sure that site admins are not present
        r4 = self.generate_researcher(site_admin=True)
        resp = self.do_test_status_code(200)
        self.assert_not_present(r4.username, resp.content)
        
        # make sure that unaffiliated researchers are not present
        r5 = self.generate_researcher()
        resp = self.do_test_status_code(200)
        self.assert_not_present(r5.username, resp.content)
    
    def test_render_site_admin(self):
        self.session_researcher.update(site_admin=True)
        self._test_render_with_researchers()
        # make sure that site admins ARE present
        r4 = self.generate_researcher(site_admin=True)
        resp = self.do_test_status_code(200)
        self.assert_present(r4.username, resp.content)
        
        # make sure that unaffiliated researchers ARE present
        r5 = self.generate_researcher()
        resp = self.do_test_status_code(200)
        self.assert_present(r5.username, resp.content)
    
    def _test_render_with_researchers(self):
        # render the page with a regular user
        r2 = self.generate_researcher(relation_to_session_study=ResearcherRole.researcher)
        resp = self.do_test_status_code(200)
        self.assert_present(r2.username, resp.content)
        
        # render with 2 reseaorchers
        r3 = self.generate_researcher(relation_to_session_study=ResearcherRole.researcher)
        resp = self.do_test_status_code(200)
        self.assert_present(r2.username, resp.content)
        self.assert_present(r3.username, resp.content)


class TestEditResearcher(GeneralPageTest):
    ENDPOINT_NAME = "system_admin_pages.edit_researcher"
    
    # render self
    def test_render_for_self_as_researcher(self):
        # should fail
        self.set_session_study_relation()
        self.do_test_status_code(403, self.session_researcher.id)
    
    def test_render_for_self_as_study_admin(self):
        # ensure it renders (buttons will be disabled)
        self.set_session_study_relation(ResearcherRole.study_admin)
        self.do_test_status_code(200, self.session_researcher.id)
    
    def test_render_for_self_as_site_admin(self):
        # ensure it renders (buttons will be disabled)
        self.session_researcher.update(site_admin=True)
        self.do_test_status_code(200, self.session_researcher.id)
    
    def test_render_for_researcher_as_researcher(self):
        # should fail
        self.set_session_study_relation()
        # set up, test when not on study
        r2 = self.generate_researcher()
        resp = self.do_test_status_code(403, r2.id)
        self.assert_not_present(r2.username, resp.content)
        # attach other researcher and try again
        self.generate_study_relation(r2, self.session_study, ResearcherRole.researcher)
        resp = self.do_test_status_code(403, r2.id)
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
        self.session_researcher.update(site_admin=True)
        self._test_render_generic_under_study()
    
    def test_render_researcher_with_no_study_as_site_admin(self):
        self.session_researcher.update(site_admin=True)
        self._test_render_researcher_with_no_study()
    
    def _test_render_generic_under_study(self):
        r2 = self.generate_researcher(relation_to_session_study=ResearcherRole.researcher)
        resp = self.do_test_status_code(200, r2.id)
        self.assert_present(r2.username, resp.content)
    
    def _test_render_researcher_with_no_study(self):
        r2 = self.generate_researcher()
        resp = self.do_test_status_code(200, r2.id)
        self.assert_present(r2.username, resp.content)


class TestElevateResearcher(SessionApiTest):
    ENDPOINT_NAME = "system_admin_pages.elevate_researcher"
    # (this one is tedious.)
    
    def test_self_as_researcher_on_study(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.do_test_status_code(
            403, researcher_id=self.session_researcher.id, study_id=self.session_study.id
        )
    
    def test_self_as_study_admin_on_study(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self.do_test_status_code(
            403, researcher_id=self.session_researcher.id, study_id=self.session_study.id
        )
    
    def test_researcher_as_study_admin_on_study(self):
        # this is the only case that succeeds
        self.set_session_study_relation(ResearcherRole.study_admin)
        r2 = self.generate_researcher(relation_to_session_study=ResearcherRole.researcher)
        self.do_test_status_code(302, researcher_id=r2.id, study_id=self.session_study.id)
        self.assertEqual(r2.study_relations.get().relationship, ResearcherRole.study_admin)
    
    def test_study_admin_as_study_admin_on_study(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        r2 = self.generate_researcher(relation_to_session_study=ResearcherRole.study_admin)
        self.do_test_status_code(403, researcher_id=r2.id, study_id=self.session_study.id)
        self.assertEqual(r2.study_relations.get().relationship, ResearcherRole.study_admin)
    
    def test_site_admin_as_study_admin_on_study(self):
        self.session_researcher
        self.set_session_study_relation(ResearcherRole.study_admin)
        r2 = self.generate_researcher(site_admin=True)
        self.do_test_status_code(403, researcher_id=r2.id, study_id=self.session_study.id)
        self.assertFalse(r2.study_relations.filter(study=self.session_study).exists())
    
    def test_site_admin_as_site_admin(self):
        self.session_researcher.update(site_admin=True)
        r2 = self.generate_researcher(site_admin=True)
        self.do_test_status_code(403, researcher_id=r2.id, study_id=self.session_study.id)
        self.assertFalse(r2.study_relations.filter(study=self.session_study).exists())


class TestDemoteStudyAdmin(SessionApiTest):
    # FIXME: this endpoint does not test for site admin cases correctly, the test passes but is
    # wrong. Behavior is fine because it has no relevant side effects except for the know bug where
    # site admins need to be manually added to a study before being able to download data.
    ENDPOINT_NAME = "system_admin_pages.demote_study_admin"
    
    def test_researcher_as_researcher(self):
        r2 = self.generate_researcher(relation_to_session_study=ResearcherRole.researcher)
        self.do_test_status_code(403, researcher_id=r2.id, study_id=self.session_study.id)
        self.assertEqual(r2.study_relations.get().relationship, ResearcherRole.researcher)
    
    def test_researcher_as_study_admin(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        r2 = self.generate_researcher(relation_to_session_study=ResearcherRole.researcher)
        self.do_test_status_code(302, researcher_id=r2.id, study_id=self.session_study.id)
        self.assertEqual(r2.study_relations.get().relationship, ResearcherRole.researcher)
    
    def test_study_admin_as_admin(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        r2 = self.generate_researcher(relation_to_session_study=ResearcherRole.study_admin)
        self.do_test_status_code(302, researcher_id=r2.id, study_id=self.session_study.id)
        self.assertEqual(r2.study_relations.get().relationship, ResearcherRole.researcher)
    
    def test_site_admin_as_study_admin(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        r2 = self.generate_researcher(site_admin=True)
        self.do_test_status_code(302, researcher_id=r2.id, study_id=self.session_study.id)
        self.assertFalse(r2.study_relations.exists())
        r2.refresh_from_db()
        self.assertTrue(r2.site_admin)
    
    def test_site_admin_as_site_admin(self):
        self.session_researcher.update(site_admin=True)
        self.set_session_study_relation(ResearcherRole.study_admin)
        r2 = self.generate_researcher(site_admin=True)
        self.do_test_status_code(302, researcher_id=r2.id, study_id=self.session_study.id)
        self.assertFalse(r2.study_relations.exists())
        r2.refresh_from_db()
        self.assertTrue(r2.site_admin)


class TestCreateNewResearcher(SessionApiTest):
    """ Admins should be able to create and load the page. """
    ENDPOINT_NAME = "system_admin_pages.create_new_researcher"
    
    def test_load_page_at_endpoint(self):
        # This test should be transformed into a separate endpoint
        for user_role in ALL_RESEARCHER_TYPES:
            prior_researcher_count = Researcher.objects.count()
            self.assign_role(self.session_researcher, user_role)
            resp = self.client.get(reverse(self.ENDPOINT_NAME))
            if user_role in ADMIN_ROLES:
                self.assertEqual(resp.status_code, 200)
            else:
                self.assertEqual(resp.status_code, 403)
            self.assertEqual(prior_researcher_count, Researcher.objects.count())
    
    def test_create_researcher(self):
        for user_role in ALL_RESEARCHER_TYPES:
            prior_researcher_count = Researcher.objects.count()
            self.assign_role(self.session_researcher, user_role)
            username = generate_easy_alphanumeric_string()
            password = generate_easy_alphanumeric_string()
            resp = self.smart_post(admin_id=username, password=password)
            
            if user_role in ADMIN_ROLES:
                self.assertEqual(resp.status_code, 302)
                self.assertEqual(prior_researcher_count + 1, Researcher.objects.count())
                self.assertTrue(Researcher.check_password(username, password))
            else:
                self.assertEqual(resp.status_code, 403)
                self.assertEqual(prior_researcher_count, Researcher.objects.count())


class TestManageStudies(GeneralPageTest):
    """ All we do with this page is make sure it loads... there isn't much to hook onto and
    determine a failure or a success... the study names are always present in the json on the
    html... """
    ENDPOINT_NAME = "system_admin_pages.manage_studies"
    
    def test(self):
        for user_role in ALL_TESTING_ROLES:
            self.assign_role(self.session_researcher, user_role)
            resp = self.smart_get()
            if user_role in ADMIN_ROLES:
                self.assertEqual(resp.status_code, 200)
            else:
                self.assertEqual(resp.status_code, 403)


class TestEditStudy(GeneralPageTest):
    """ Test basics of permissions, test details of the study are appropriately present on page... """
    ENDPOINT_NAME = "system_admin_pages.edit_study"
    
    def test_only_admins_allowed(self):
        for user_role in ALL_TESTING_ROLES:
            self.assign_role(self.session_researcher, user_role)
            self.do_test_status_code(
                status_code=200 if user_role in ADMIN_ROLES else 403,
                study_id=self.session_study.id
            )
    
    def test_content_study_admin(self):
        """ tests that various important pieces of information are present """
        self.set_session_study_relation(ResearcherRole.study_admin)
        self.session_study.update(is_test=True, forest_enabled=False)
        resp = self.do_test_status_code(200, study_id=self.session_study.id)
        self.assert_present("Forest is currently disabled.", resp.content)
        self.assert_present("This is a test study", resp.content)
        self.assert_present(self.session_researcher.username, resp.content)
        
        self.session_study.update(is_test=False, forest_enabled=True)
        r2 = self.generate_researcher(relation_to_session_study=ResearcherRole.researcher)
        
        resp = self.do_test_status_code(200, study_id=self.session_study.id)
        self.assert_present(self.session_researcher.username, resp.content)
        self.assert_present(r2.username, resp.content)
        self.assert_present("Forest is currently enabled.", resp.content)
        self.assert_present("This is a production study", resp.content)


# FIXME: need to implement tests for copy study.
# FIXME: this test is not well factored, it doesn't follow a common pattern.
class TestCreateStudy(SessionApiTest):
    ENDPOINT_NAME = "system_admin_pages.create_study"
    NEW_STUDY_NAME = "something anything"
    
    @property
    def get_the_new_study(self):
        return Study.objects.get(name=self.NEW_STUDY_NAME)
    
    def create_study_params(self, *except_these: List[str]):
        """ keys are: name, encryption_key, is_test, copy_existing_study, forest_enabled """
        params = dict(
            name=self.NEW_STUDY_NAME,
            encryption_key="a" * 32,
            is_test="true",
            copy_existing_study="",
            forest_enabled="false",
        )
        for k in except_these:
            params.pop(k)
        return params
    
    def test_load_page(self):
        # only site admins can load the page
        for user_role in ALL_TESTING_ROLES:
            self.assign_role(self.session_researcher, user_role)
            self.do_test_status_code(302 if user_role == "site_admin" else 403)
    
    def test_create_study_success(self):
        self.session_researcher.update(site_admin=True)
        resp = self.do_test_status_code(302, **self.create_study_params())
        self.assertIsInstance(resp, HttpResponseRedirect)
        target_url = easy_url(
            "system_admin_pages.device_settings", study_id=self.get_the_new_study.id
        )
        self.assertEqual(resp.url, target_url)
        resp = self.client.get(target_url)
        self.assertEqual(resp.status_code, 200)
        self.assert_present(f"Successfully created study {self.get_the_new_study.name}.", resp.content)
    
    def test_create_study_long_name(self):
        # this situation reports to sentry manually, the response is a hard 400, no calls to messages
        self.session_researcher.update(site_admin=True)
        params = self.create_study_params()
        params["name"] = "a"*10000
        resp = self.do_test_status_code(400, **params)
        self.assertEqual(resp.content, b"")
    
    def test_create_study_bad_name(self):
        # this situation reports to sentry manually, the response is a hard 400, no calls to messages
        self.session_researcher.update(site_admin=True)
        params = self.create_study_params()
        params["name"] = "&" * 50
        resp = self.do_test_status_code(400, **params)
        self.assertEqual(resp.content, b"")


# FIXME: this test has the annoying un-factored url with post params and url params
class TestToggleForest(RedirectSessionApiTest):
    ENDPOINT_NAME = "system_admin_pages.toggle_study_forest_enabled"
    REDIRECT_ENDPOINT_NAME = "system_admin_pages.edit_study"
    
    def test_toggle_on(self):
        resp = self._do_test_toggle(True)
        self.assert_present("Enabled Forest on", resp.content)
    
    def test_toggle_off(self):
        resp = self._do_test_toggle(False)
        self.assert_present("Disabled Forest on", resp.content)
    
    def _do_test_toggle(self, enable: bool):
        redirect_endpoint = easy_url(self.REDIRECT_ENDPOINT_NAME, study_id=self.session_study.id)
        self.session_researcher.update(site_admin=True)
        self.session_study.update(forest_enabled=not enable)  # directly mutate the database.
        # resp = self.smart_post(study_id=self.session_study.id)  # nope this does not follow the normal pattern
        resp = self.smart_post(self.session_study.id)
        self.assertEqual(resp.url, redirect_endpoint)
        self.session_study.refresh_from_db()
        if enable:
            self.assertTrue(self.session_study.forest_enabled)
        else:
            self.assertFalse(self.session_study.forest_enabled)
        return self.client.get(redirect_endpoint)


# FIXME: this test has the annoying un-factored url with post params and url params
class TestDeleteStudy(RedirectSessionApiTest):
    ENDPOINT_NAME = "system_admin_pages.delete_study"
    REDIRECT_ENDPOINT_NAME = "system_admin_pages.manage_studies"
    
    def test_success(self):
        self.session_researcher.update(site_admin=True)
        resp = self.smart_post(self.session_study.id, confirmation="true")
        self.session_study.refresh_from_db()
        self.assertTrue(self.session_study.deleted)
        self.assertEqual(resp.url, easy_url(self.REDIRECT_ENDPOINT_NAME))
        self.assert_present("Deleted study ", self.get_redirect_content())


class TestDeviceSettings(SessionApiTest):
    ENDPOINT_NAME = "system_admin_pages.device_settings"
    
    CONSENT_SECTIONS = {
        'consent_sections.data_gathering.more': 'a',
        'consent_sections.data_gathering.text': 'b',
        'consent_sections.privacy.more': 'c',
        'consent_sections.privacy.text': 'd',
        'consent_sections.study_survey.more': 'e',
        'consent_sections.study_survey.text': 'f',
        'consent_sections.study_tasks.more': 'g',
        'consent_sections.study_tasks.text': 'h',
        'consent_sections.time_commitment.more': 'i',
        'consent_sections.time_commitment.text': 'j',
        'consent_sections.welcome.more': 'k',
        'consent_sections.welcome.text': 'l',
        'consent_sections.withdrawing.more': 'm',
        'consent_sections.withdrawing.text': 'n',
    }
    
    BOOLEAN_FIELD_NAMES = [
        field.name
        for field in DeviceSettings._meta.fields
        if isinstance(field, (models.BooleanField, NullBooleanField))
    ]
    
    def invert_boolean_checkbox_fields(self, some_dict):
        for field in self.BOOLEAN_FIELD_NAMES:
            if field in some_dict and bool(some_dict[field]):
                some_dict.pop(field)
            else:
                some_dict[field] = "true"
    
    @staticmethod
    def mutate_variable(var):
        # ah, checkboxes are bizarre, use invert_checkboxes
        if isinstance(var, bool):
            return var  # don't change here, use invert_boolean_checkbox_fields
        elif isinstance(var, (float, int)):
            return var + 1
        elif isinstance(var, str):
            return var + "aaa"
        else:
            raise TypeError(f"Unhandled type: {type(var)}")
    
    def test_get(self):
        for role in ALL_TESTING_ROLES:
            self.assign_role(self.session_researcher, role)
            resp = self.smart_get(self.session_study.id)
            self.assertEqual(resp.status_code, 200 if role is not None else 403)
    
    def test_study_admin(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self.do_test_update()
    
    def test_site_admin(self):
        self.session_researcher.update(site_admin=True)
        self.do_test_update()
    
    def do_test_update(self):
        """ This test mimics the frontend input (checkboxes are a little strange and require setup).
        The test mutates all fields in the input that is sent to the backend, and confirms that every
        field pushed changed. """
        
        # extract data from database (it is all default values, unpacking jsonstrings)
        # created_on and last_updated are already absent
        post_params = self.session_device_settings.as_unpacked_native_python()
        old_device_settings = copy(post_params)
        post_params.pop("id")
        post_params.pop("consent_sections")  # this is not present in the form
        post_params.update(**self.CONSENT_SECTIONS)
        
        # mutate everything
        post_params = {k: self.mutate_variable(v) for k, v in post_params.items()}
        self.invert_boolean_checkbox_fields(post_params)
        
        # Hit endpoint
        self.do_test_status_code(302, self.session_study.id, **post_params)
        
        # Test database update, get new data, extract consent sections.
        self.assertEqual(DeviceSettings.objects.count(), 1)
        new_device_settings = DeviceSettings.objects.first().as_unpacked_native_python()
        new_device_settings.pop("id")
        old_consent_sections = old_device_settings.pop("consent_sections")
        new_consent_sections = new_device_settings.pop("consent_sections")
        
        for k, v in new_device_settings.items():
            # boolean values are set to true or false based on presence in the post request,
            # that's how checkboxes work.
            if k in self.BOOLEAN_FIELD_NAMES:
                if k not in post_params:
                    self.assertFalse(v)
                    self.assertTrue(old_device_settings[k])
                else:
                    self.assertTrue(v)
                    self.assertFalse(old_device_settings[k])
                continue
            
            # print(f"key: '{k}', DB: {type(v)}'{v}', post param: {type(post_params[k])} '{post_params[k]}'")
            self.assertEqual(v, post_params[k])
            self.assertNotEqual(v, old_device_settings[k])
        
        # FIXME: why does this fail?
        # Consent sections need to be unpacked, ensure they have the keys
        # self.assertEqual(set(old_consent_sections.keys()), set(new_consent_sections.keys()))
        
        for outer_key, a_dict_of_two_values in new_consent_sections.items():
            # this data structure is of the form:  {'more': 'aaaa', 'text': 'baaa'}
            self.assertEqual(len(a_dict_of_two_values), 2)
            
            # compare the inner values of every key, make sure they differ
            for inner_key, v2 in a_dict_of_two_values.items():
                self.assertNotEqual(old_consent_sections[outer_key][inner_key], v2)


class TestManageFirebaseCredentials(GeneralPageTest):
    ENDPOINT_NAME = "system_admin_pages.manage_firebase_credentials"
    
    def test(self):
        # just test that the page loads, I guess
        self.session_researcher.update(site_admin=True)
        self.do_test_status_code(200)


# FIXME: implement tests for error cases
class TestUploadBackendFirebaseCert(RedirectSessionApiTest):
    ENDPOINT_NAME = "system_admin_pages.upload_backend_firebase_cert"
    REDIRECT_ENDPOINT_NAME = "system_admin_pages.manage_firebase_credentials"
    
    @patch("pages.system_admin_pages.update_firebase_instance")
    @patch("pages.system_admin_pages.get_firebase_credential_errors")
    def test(self, get_firebase_credential_errors: MagicMock, update_firebase_instance: MagicMock):
        # test that the data makes it to the backend, patch out the errors that are sourced from the
        # firbase admin lbrary
        get_firebase_credential_errors.return_value = None
        update_firebase_instance.return_value = True
        # test upload as site admin
        self.session_researcher.update(site_admin=True)
        file = SimpleUploadedFile("backend_cert.json", BACKEND_CERT.encode(), "text/json")
        self.smart_post(backend_firebase_cert=file)
        resp_content = self.get_redirect_content()
        self.assert_present("New firebase credentials have been received", resp_content)


# FIXME: implement tests for error cases
class TestUploadIosFirebaseCert(RedirectSessionApiTest):
    ENDPOINT_NAME = "system_admin_pages.upload_ios_firebase_cert"
    REDIRECT_ENDPOINT_NAME = "system_admin_pages.manage_firebase_credentials"
    
    def test(self):
        # test upload as site admin
        self.session_researcher.update(site_admin=True)
        file = SimpleUploadedFile("ios_firebase_cert.plist", IOS_CERT.encode(), "text/json")
        self.smart_post(ios_firebase_cert=file)
        resp_content = self.get_redirect_content()
        self.assert_present("New IOS credentials were received", resp_content)


# FIXME: implement tests for error cases
class TestUploadAndroidFirebaseCert(RedirectSessionApiTest):
    ENDPOINT_NAME = "system_admin_pages.upload_android_firebase_cert"
    REDIRECT_ENDPOINT_NAME = "system_admin_pages.manage_firebase_credentials"
    
    def test(self):
        # test upload as site admin
        self.session_researcher.update(site_admin=True)
        file = SimpleUploadedFile("android_firebase_cert.json", ANDROID_CERT.encode(), "text/json")
        self.smart_post(android_firebase_cert=file)
        resp_content = self.get_redirect_content()
        self.assert_present("New android credentials were received", resp_content)


class TestDeleteFirebaseBackendCert(RedirectSessionApiTest):
    ENDPOINT_NAME = "system_admin_pages.delete_backend_firebase_cert"
    REDIRECT_ENDPOINT_NAME = "system_admin_pages.manage_firebase_credentials"
    
    def test(self):
        self.session_researcher.update(site_admin=True)
        FileAsText.objects.create(tag=BACKEND_FIREBASE_CREDENTIALS, text="any_string")
        self.smart_post()
        self.assertFalse(FileAsText.objects.exists())


class TestDeleteFirebaseIosCert(RedirectSessionApiTest):
    ENDPOINT_NAME = "system_admin_pages.delete_ios_firebase_cert"
    REDIRECT_ENDPOINT_NAME = "system_admin_pages.manage_firebase_credentials"
    
    def test(self):
        self.session_researcher.update(site_admin=True)
        FileAsText.objects.create(tag=IOS_FIREBASE_CREDENTIALS, text="any_string")
        self.smart_post()
        self.assertFalse(FileAsText.objects.exists())


class TestDeleteFirebaseAndroidCert(RedirectSessionApiTest):
    ENDPOINT_NAME = "system_admin_pages.delete_android_firebase_cert"
    REDIRECT_ENDPOINT_NAME = "system_admin_pages.manage_firebase_credentials"
    
    def test(self):
        self.session_researcher.update(site_admin=True)
        FileAsText.objects.create(tag=ANDROID_FIREBASE_CREDENTIALS, text="any_string")
        self.smart_post()
        self.assertFalse(FileAsText.objects.exists())


class TestDataAccessWebFormPage(GeneralPageTest):
    ENDPOINT_NAME = "data_access_web_form.data_api_web_form_page"
    
    def test(self):
        resp = self.smart_get()
        self.assert_present("Reset Data-Download API Access Credentials", resp.content)
        id_key, secret_key = self.session_researcher.reset_access_credentials()
        resp = self.smart_get()
        self.assert_not_present("Reset Data-Download API Access Credentials", resp.content)


class TestPipelineWebFormPage(GeneralPageTest):
    ENDPOINT_NAME = "data_access_web_form.pipeline_download_page"
    
    def test(self):
        resp = self.smart_get()
        self.assert_present("Reset Data-Download API Access Credentials", resp.content)
        id_key, secret_key = self.session_researcher.reset_access_credentials()
        resp = self.smart_get()
        self.assert_not_present("Reset Data-Download API Access Credentials", resp.content)


# FIXME: add error cases to tests
class TestSetStudyTimezone(RedirectSessionApiTest):
    ENDPOINT_NAME = "admin_api.set_study_timezone"
    REDIRECT_ENDPOINT_NAME = "system_admin_pages.edit_study"
    
    def test_study_admin(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self._test_success()
    
    def test_site_admin(self):
        self.session_researcher.update(site_admin=True)
        self._test_success()
    
    def _test_success(self):
        self.smart_post(self.session_study.id, new_timezone_name="Pacific/Noumea")
        self.session_study.refresh_from_db()
        self.assertEqual(self.session_study.timezone_name, "Pacific/Noumea")
