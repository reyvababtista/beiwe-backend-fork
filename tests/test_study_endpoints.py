# trunk-ignore-all(ruff/B018)
from unittest.mock import MagicMock, patch

from constants.testing_constants import ADMIN_ROLES, ALL_TESTING_ROLES
from constants.user_constants import ResearcherRole
from libs.http_utils import easy_url
from tests.common import ResearcherSessionTest


class TestChooseStudy(ResearcherSessionTest):                     
    ENDPOINT_NAME = "study_endpoints.choose_study_page"
    # these tests tost behavior of redirection without anything in the most_recent_page tracking
    # or as forwarding from the login page via the referrer url parameter into the post parameter

    def test_2_studies(self):
        study2 = self.generate_study("study2")
        self.set_session_study_relation(ResearcherRole.researcher)
        self.generate_study_relation(self.session_researcher, study2, ResearcherRole.researcher)
        resp = self.smart_get_status_code(200)
        self.assert_present(self.session_study.name, resp.content)
        self.assert_present(study2.name, resp.content)
                                                                      
    def test_1_study(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.smart_get_status_code(302)
        self.assertEqual(
            resp.url, easy_url("study_endpoints.view_study_page", study_id=self.session_study.id)
        )

    def test_no_study(self):
        self.set_session_study_relation(None)
        resp = self.smart_get_status_code(200)
        self.assert_not_present(self.session_study.name, resp.content)


class TestViewStudy(ResearcherSessionTest):
    """ view_study is pretty simple, no custom content in the :
    tests push_notifications_enabled, study.forest_enabled
    populates html elements with custom field values
    populates html elements of survey buttons """
                                             
    ENDPOINT_NAME = "study_endpoints.view_study_page"

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

    @patch('endpoints.study_endpoints.check_firebase_instance')
    def test_view_study_site_admin(self, check_firebase_instance: MagicMock):
        study = self.session_study
        self.set_session_study_relation(ResearcherRole.site_admin)

        # test rendering with several specific values set to observe the rendering changes
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


class TestManageStudies(ResearcherSessionTest):
    """ All we do with this page is make sure it loads... there isn't much to hook onto and
    determine a failure or a success... the study names are always present in the json on the
    html... """
    ENDPOINT_NAME = "study_endpoints.manage_studies"

    def test(self):
        for user_role in ALL_TESTING_ROLES:
            self.assign_role(self.session_researcher, user_role)
            resp = self.smart_get()
            if user_role in ADMIN_ROLES:
                self.assertEqual(resp.status_code, 200)
            else:
                self.assertEqual(resp.status_code, 403)


class TestEditStudy(ResearcherSessionTest):
    """ Test basics of permissions, test details of the study are appropriately present on page... """
    ENDPOINT_NAME = "study_endpoints.edit_study"

    def test_only_admins_allowed(self):
        for user_role in ALL_TESTING_ROLES:
            self.assign_role(self.session_researcher, user_role)
            self.smart_get_status_code(
                200 if user_role in ADMIN_ROLES else 403, self.session_study.id
            )

    def test_content_study_admin(self):
        """ tests that various important pieces of information are present """
        self.set_session_study_relation(ResearcherRole.study_admin)
        self.session_study.update(forest_enabled=False)
        resp1 = self.smart_get_status_code(200, self.session_study.id)
        self.assert_present("Enable Forest", resp1.content)
        self.assert_not_present("Disable Forest", resp1.content)
        self.assert_present(self.session_researcher.username, resp1.content)

        self.session_study.update(forest_enabled=True)
        r2 = self.generate_researcher(relation_to_session_study=ResearcherRole.researcher)

        # tests for presence of own username and other researcher's username in the html
        resp2 = self.smart_get_status_code(200, self.session_study.id)
        self.assert_present(self.session_researcher.username, resp2.content)
        self.assert_present(r2.username, resp2.content)
        # assertInHTML is several hundred times slower but has much better output when it fails...
        # self.assertInHTML("Configure Interventions for use with Relative survey schedules", response.content.decode())
