from datetime import date

import orjson

from authentication.tableau_authentication import (check_tableau_permissions,
    TableauAuthenticationFailed, TableauPermissionDenied)
from constants.tableau_api_constants import (SERIALIZABLE_FIELD_NAMES, X_ACCESS_KEY_ID,
    X_ACCESS_KEY_SECRET)
from database.security_models import ApiKey
from database.user_models import StudyRelation
from tests.common import ResearcherSessionTest, TableauAPITest
from tests.helpers import compare_dictionaries


class TestNewTableauAPIKey(ResearcherSessionTest):
    ENDPOINT_NAME = "admin_pages.new_tableau_api_key"
    
    def test_new_api_key(self):
        """ Asserts that:
            -one new api key is added to the database
            -that api key is linked to the logged in researcher
            -the correct readable name is associated with the key
            -no other api keys were created associated with that researcher
            -that api key is active and has tableau access  """
        self.assertEqual(ApiKey.objects.count(), 0)
        resp = self.smart_post(readable_name="test_generated_api_key")
        self.assertEqual(ApiKey.objects.count(), 1)
        api_key = ApiKey.objects.get(readable_name="test_generated_api_key")
        self.assertEqual(api_key.researcher.id, self.session_researcher.id)
        self.assertTrue(api_key.is_active)
        self.assertTrue(api_key.has_tableau_api_permissions)


class TestDisableTableauAPIKey(TableauAPITest):
    ENDPOINT_NAME = "admin_pages.disable_tableau_api_key"
    
    def test_disable_tableau_api_key(self):
        """ Asserts that:
            -exactly one fewer active api key is present in the database
            -the api key is no longer active """
        self.assertEqual(ApiKey.objects.filter(is_active=True).count(), 1)
        self.smart_post(api_key_id=self.api_key_public)
        self.assertEqual(ApiKey.objects.filter(is_active=True).count(), 0)
        self.assertFalse(ApiKey.objects.get(access_key_id=self.api_key_public).is_active)


class TestGetTableauDaily(TableauAPITest):
    ENDPOINT_NAME = "tableau_api.get_tableau_daily"
    
    # parameters are
    # end_date, start_date, limit, order_by, order_direction, participant_ids, fields
    
    # helpers
    @property
    def post_params_all_fields(self):
        headers = self.raw_headers
        headers["fields"] = ",".join(SERIALIZABLE_FIELD_NAMES)
        return headers
    
    @property
    def post_params_all_defaults(self):
        headers = self.post_params_all_fields
        headers['participant_ids'] = self.default_participant.patient_id
        return headers
    
    @property
    def full_response_dict(self):
        defaults = self.default_summary_statistic_daily_cheatsheet()
        defaults["date"] = date.today().isoformat()
        defaults["participant_id"] = self.default_participant.id
        defaults["study_id"] = self.session_study.object_id
        return defaults
    
    def test_summary_statistics_daily_no_params_empty_db(self):
        # unpack the raw headers like this, they magically just work because http language is weird
        resp = self.smart_get_status_code(200, self.session_study.object_id, **self.raw_headers)
        response_content = b"".join(resp.streaming_content)
        self.assertEqual(response_content, b'[]')
    
    def test_summary_statistics_daily_all_params_empty_db(self):
        headers = self.post_params_all_fields
        resp = self.smart_get_status_code(200, self.session_study.object_id, **headers)
        response_content = b"".join(resp.streaming_content)
        self.assertEqual(response_content, b'[]')
    
    def test_summary_statistics_daily_all_params_all_populated(self):
        headers = self.post_params_all_defaults
        self.generate_summary_statistic_daily()
        resp = self.smart_get_status_code(200, self.session_study.object_id, **headers)
        response_content = b"".join(resp.streaming_content)
        response_json = orjson.loads(response_content)
        self.assertEqual(len(response_json), 1)
        assert compare_dictionaries(response_json[0], self.full_response_dict)


class TableauApiAuthTests(TableauAPITest):
    """ Test methods of the api authentication system """
    ENDPOINT_NAME = TableauAPITest.IGNORE_THIS_ENDPOINT
    
    def test_check_permissions_working(self):
        # if this doesn't raise an error in has succeeded
        check_tableau_permissions(self.default_header, study_object_id=self.session_study.object_id)
    
    def test_check_permissions_none(self):
        ApiKey.objects.all().delete()
        with self.assertRaises(TableauAuthenticationFailed) as cm:
            check_tableau_permissions(
                self.default_header, study_object_id=self.session_study.object_id
            )
    
    def test_check_permissions_inactive(self):
        self.api_key.update(is_active=False)
        with self.assertRaises(TableauAuthenticationFailed) as cm:
            check_tableau_permissions(
                self.default_header, study_object_id=self.session_study.object_id
            )
    
    def test_check_permissions_bad_secret(self):
        # note that ':' does not appear in base64 encoding, preventing any collision errors based on
        # the current implementation.
        class NotRequest:
            headers = {
                X_ACCESS_KEY_ID: self.api_key_public,
                X_ACCESS_KEY_SECRET: ":::" + self.api_key_private[3:],
            }
        with self.assertRaises(TableauAuthenticationFailed) as cm:
            check_tableau_permissions(
                NotRequest, study_object_id=self.session_study.object_id
            )
    
    def test_check_permissions_no_tableau(self):
        self.api_key.update(has_tableau_api_permissions=False)
        # ApiKey.objects.filter(access_key_id=self.api_key_public).update(
        #     has_tableau_api_permissions=False
        # )
        with self.assertRaises(TableauPermissionDenied) as cm:
            check_tableau_permissions(
                self.default_header, study_object_id=self.session_study.object_id
            )
    
    def test_check_permissions_bad_study(self):
        self.assertFalse(ApiKey.objects.filter(access_key_id=" bad study id ").exists())
        with self.assertRaises(TableauPermissionDenied) as cm:
            check_tableau_permissions(
                self.default_header, study_object_id=" bad study id "
            )
    
    def test_check_permissions_no_study_permission(self):
        StudyRelation.objects.filter(
            study=self.session_study, researcher=self.session_researcher).delete()
        with self.assertRaises(TableauPermissionDenied) as cm:
            check_tableau_permissions(
                self.default_header, study_object_id=self.session_study.object_id
            )
