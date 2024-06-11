import json
from datetime import datetime

import orjson
from dateutil.tz import UTC
from django.core.exceptions import ValidationError

from constants.data_access_api_constants import MISSING_JSON_CSV_MESSAGE
from constants.tableau_api_constants import SERIALIZABLE_FIELD_NAMES
from constants.user_constants import ResearcherRole
from database.profiling_models import UploadTracking
from database.security_models import ApiKey
from database.study_models import Study
from database.survey_models import Survey, SurveyArchive
from database.user_models_participant import AppHeartbeats
from libs.participant_table_api import get_table_columns
from tests.common import DataApiTest


# trunk-ignore-all(ruff/B018)

#
## other_data_apis
#


class TestAPIGetStudies(DataApiTest):
    ENDPOINT_NAME = "other_data_apis.get_studies"
    
    def test_inactive_credentials(self):
        """ this test serves as a test of authentication database details. """
        self.API_KEY.is_active = False
        self.API_KEY.save()
        self.smart_post_status_code(403)
        self.API_KEY.refresh_from_db()
        self.assertFalse(self.API_KEY.is_active)  # don't change it yet
        self.assertIsNone(self.API_KEY.last_used)
        
        self.API_KEY.update_only(is_active=True) # ok now change it
        self.smart_post_status_code(200)
        self.API_KEY.refresh_from_db()
        self.assertIsInstance(self.API_KEY.last_used, datetime)
    
    def test_no_study(self):
        resp = self.smart_post_status_code(200)
        self.assertEqual(Study.objects.count(), 0)
        self.assertEqual(json.loads(resp.content), {})
    
    def test_no_study_relation(self):
        resp = self.smart_post_status_code(200)
        self.session_study
        self.assertEqual(Study.objects.count(), 1)
        self.assertEqual(json.loads(resp.content), {})
    
    def test_multiple_studies_one_relation(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.generate_study("study2")
        resp = self.smart_post_status_code(200)
        self.assertEqual(
            json.loads(resp.content), {self.session_study.object_id: self.DEFAULT_STUDY_NAME}
        )
    
    def test_study_relation(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.smart_post_status_code(200)
        self.assertEqual(
            json.loads(resp.content), {self.session_study.object_id: self.DEFAULT_STUDY_NAME}
        )
    
    def test_multiple_studies(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        study2 = self.generate_study("study2")
        self.generate_study_relation(self.session_researcher, study2, ResearcherRole.researcher)
        resp = self.smart_post_status_code(200)
        self.assertEqual(
            json.loads(resp.content), {
                self.session_study.object_id: self.DEFAULT_STUDY_NAME,
                study2.object_id: study2.name
            }
        )


class TestApiCredentialCheck(DataApiTest):
    ENDPOINT_NAME = "other_data_apis.get_studies"
    
    def test_missing_all_parameters(self):
        # use _smart_post
        resp = self.less_smart_post()
        # 400, missing parameter
        self.assertEqual(400, resp.status_code)
    
    def test_only_secret_key(self):
        resp = self.less_smart_post(secret_key=self.session_secret_key)
        # 400, missing parameter
        self.assertEqual(400, resp.status_code)
    
    def test_only_access_key(self):
        resp = self.less_smart_post(access_key=self.session_access_key)
        # 400, missing parameter
        self.assertEqual(400, resp.status_code)
    
    def test_regex_validation(self):
        # asserts that the regex validation is working on te secret key
        self.API_KEY.access_key_secret = "apples"
        self.assertRaises(ValidationError, self.API_KEY.save)
    
    def test_wrong_secret_key_db(self):
        # Weird, but keep it, useful when debugging this test.
        # the_id = self.session_researcher.id  # instantiate the researcher, get their id
        # have to bypass validation
        ApiKey.objects.filter(id=self.API_KEY.id).update(access_key_secret="apples")
        resp = self.smart_post()
        # key doesn't match, forbidden
        self.assertEqual(403, resp.status_code)
    
    def test_wrong_secret_key_post(self):
        resp = self.less_smart_post(access_key="apples", secret_key=self.session_secret_key)
        # key doesn't match, forbidden
        self.assertEqual(403, resp.status_code)
    
    def test_wrong_access_key_db(self):
        # Weird, but keep it, useful when debugging this test.
        self.API_KEY.access_key_id = "apples"
        self.API_KEY.save()
        resp = self.smart_post()
        # no such user, forbidden
        self.assertEqual(403, resp.status_code)
    
    def test_wrong_access_key_post(self):
        resp = self.less_smart_post(access_key=self.session_access_key, secret_key="apples")
        # no such user, forbidden
        self.assertEqual(403, resp.status_code)
    
    def test_access_key_special_characters(self):
        self.session_access_key = "\x00" * 64
        self.smart_post_status_code(400)
    
    def test_secret_key_special_characters(self):
        self.session_secret_key = "\x00" * 64
        self.smart_post_status_code(400)
    
    def test_site_admin(self):
        self.assign_role(self.session_researcher, ResearcherRole.site_admin)
        self.smart_post_status_code(200)
    
    def test_researcher(self):
        self.assign_role(self.session_researcher, ResearcherRole.study_admin)
        self.smart_post_status_code(200)
    
    def test_study_admin(self):
        self.assign_role(self.session_researcher, ResearcherRole.researcher)
        self.smart_post_status_code(200)


class TestAPIStudyUserAccess(DataApiTest):
    ENDPOINT_NAME = "other_data_apis.get_users_in_study"
    
    def test_missing_all_parameters(self):
        # self.set_session_study_relation(ResearcherRole)
        # use _smart_post
        resp = self.less_smart_post()
        # 400, missing parameter
        self.assertEqual(400, resp.status_code)
    
    def test_only_secret_key(self):
        resp = self.less_smart_post(secret_key=self.session_secret_key)
        # 400, missing parameter
        self.assertEqual(400, resp.status_code)
    
    def test_only_access_key(self):
        resp = self.less_smart_post(access_key=self.session_access_key)
        # 400, missing parameter
        self.assertEqual(400, resp.status_code)
    
    def test_only_study_obj_id(self):
        resp = self.less_smart_post(study_id=self.session_study.object_id)
        # 400, missing parameter
        self.assertEqual(400, resp.status_code)
    
    def test_only_study_pk(self):
        resp = self.less_smart_post(study_pk=self.session_study.pk)
        # 400, missing parameter
        self.assertEqual(400, resp.status_code)
    
    def test_wrong_secret_key_post(self):
        resp = self.less_smart_post(
            access_key="apples", secret_key=self.session_secret_key, study_pk=self.session_study.pk
        )
        # key doesn't match, forbidden
        self.assertEqual(403, resp.status_code)
    
    def test_wrong_access_key_post(self):
        resp = self.less_smart_post(
            access_key=self.session_access_key, secret_key="apples", study_pk=self.session_study.pk
        )
        # no such user, forbidden
        self.assertEqual(403, resp.status_code)
    
    def test_no_such_study_pk(self):
        # 0 is an invalid study id
        self.smart_post_status_code(404, study_pk=0)
    
    def test_no_such_study_obj(self):
        # 0 is an invalid study id
        self.smart_post_status_code(404, study_id='a' * 24)
    
    def test_bad_object_id(self):
        # 0 is an invalid study id
        self.smart_post_status_code(400, study_id='[' * 24)
        self.smart_post_status_code(400, study_id='a' * 5)
    
    def test_access_key_special_characters(self):
        self.session_access_key = "\x00" * 64
        self.smart_post_status_code(400, study_pk=self.session_study.pk)
    
    def test_secret_key_special_characters(self):
        self.session_secret_key = "\x00" * 64
        self.smart_post_status_code(400, study_pk=self.session_study.pk)
    
    def test_site_admin(self):
        self.assign_role(self.session_researcher, ResearcherRole.site_admin)
        self.smart_post_status_code(200, study_pk=self.session_study.pk)
    
    def test_researcher(self):
        self.assign_role(self.session_researcher, ResearcherRole.study_admin)
        self.smart_post_status_code(200, study_pk=self.session_study.pk)
    
    def test_study_admin(self):
        self.assign_role(self.session_researcher, ResearcherRole.researcher)
        self.smart_post_status_code(200, study_pk=self.session_study.pk)
    
    def test_no_relation(self):
        self.assign_role(self.session_researcher, None)
        self.smart_post_status_code(403, study_pk=self.session_study.pk)


class TestGetUsersInStudy(DataApiTest):
    ENDPOINT_NAME = "other_data_apis.get_users_in_study"
    
    def test_no_participants(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.smart_post_status_code(200, study_id=self.session_study.object_id)
        self.assertEqual(resp.content, b"[]")
    
    def test_one_participant(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        resp = self.smart_post_status_code(200, study_id=self.session_study.object_id)
        self.assertEqual(resp.content, f'["{self.default_participant.patient_id}"]'.encode())
    
    def test_two_participants(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        p2 = self.generate_participant(self.session_study)
        resp = self.smart_post_status_code(200, study_id=self.session_study.object_id)
        # ordering here is random because generate_participant is random, so we will just test both.
        match = f'["{self.default_participant.patient_id}", "{p2.patient_id}"]'
        match2 = f'["{p2.patient_id}", "{self.default_participant.patient_id}"]'
        try:
            self.assertEqual(resp.content, match.encode())
        except AssertionError:
            self.assertEqual(resp.content, match2.encode())


class TestDownloadStudyInterventions(DataApiTest):
    ENDPOINT_NAME = "other_data_apis.download_study_interventions"
    
    def test_no_interventions(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.smart_post_status_code(200, study_id=self.session_study.object_id)
        self.assertEqual(resp.content, b"{}")
    
    def test_survey_with_one_intervention(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_populated_intervention_date
        self.default_relative_schedule
        resp = self.smart_post_status_code(200, study_id=self.session_study.object_id)
        json_unpacked = json.loads(resp.content)
        correct_output = {
            self.DEFAULT_PARTICIPANT_NAME:
                {
                    self.DEFAULT_SURVEY_OBJECT_ID:
                        {
                            self.DEFAULT_INTERVENTION_NAME: self.CURRENT_DATE.isoformat()
                        }
                }
        }
        self.assertDictEqual(json_unpacked, correct_output)


class TestStudySurveyHistory(DataApiTest):
    ENDPOINT_NAME = "other_data_apis.download_study_survey_history"
    
    def test_no_surveys(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.smart_post_status_code(200, study_id=self.session_study.object_id)
        ret = b"".join(resp.streaming_content)
        # the output is a dictionary with survey ids as keys
        self.assertEqual(ret, b"{}")
    
    def test_one_survey_two_archives(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_survey
        
        self.assertEqual(Survey.objects.count(), 1)
        self.assertEqual(SurveyArchive.objects.count(), 1)
        self.default_survey.content = '["a_string"]'
        self.default_survey.archive()
        self.assertEqual(SurveyArchive.objects.count(), 2)
        
        # for archive in SurveyArchive.objects.all():
            
        resp = self.smart_post_status_code(200, study_id=self.session_study.object_id)
        should_be = '{"u1Z3SH7l2xNsw72hN3LnYi96":[{"archive_start":'\
                    '"replace1","survey_json":[]},{"archive_start":'\
                    '"replace2","survey_json":["a_string"]}]}'
        archive1, archive2 = SurveyArchive.objects.all()
        should_be = should_be.replace("replace1", archive1.archive_start.isoformat())
        should_be = should_be.replace("replace2", archive2.archive_start.isoformat())
        ret = b"".join(resp.streaming_content)
        self.assertEqual(ret, should_be.encode())
    
    def test_one_survey_one_archive(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_survey
        self.assertEqual(Survey.objects.count(), 1)
        self.assertEqual(SurveyArchive.objects.count(), 1)
        archive = self.default_survey.most_recent_archive()
        resp = self.smart_post_status_code(200, study_id=self.session_study.object_id)
        should_be = b'{"u1Z3SH7l2xNsw72hN3LnYi96":[{"archive_start":"replace","survey_json":[]}]}'
        should_be = should_be.replace(b"replace", archive.archive_start.isoformat().encode())
        ret = b"".join(resp.streaming_content)
        self.assertEqual(ret, should_be)


class TestDownloadParticipantTableData(DataApiTest):
    ENDPOINT_NAME = "other_data_apis.get_participant_table_data"
    json_table_default_columns = \
    b'["Created On","Patient ID","Status","OS Type","Last Upload","Last Survey Download",' \
        b'"Last Registration","Last Set Password","Last Push Token Update","Last Device Settings ' \
        b'Update","Last OS Version","App Version Code","App Version Name","Last Heartbeat"]'
    
    def test_no_study_param(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.smart_post_status_code(400)
    
    def test_missing_data_param(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.smart_post_status_code(400, study_id=self.session_study.object_id)
        self.assertEqual(resp.content, MISSING_JSON_CSV_MESSAGE)
    
    def test_data_format_param_wrong(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.smart_post_status_code(400, study_id=self.session_study.object_id, data_format="apples")
        self.assertEqual(resp.content, MISSING_JSON_CSV_MESSAGE)
    
    def test_no_data_csv(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.smart_post_status_code(200, study_id=self.session_study.object_id, data_format="csv")
        # its just the header row and a \r\n
        self.assertEqual(resp.content, (",".join(get_table_columns(self.session_study)) + "\r\n").encode())
    
    def test_no_data_json(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.smart_post_status_code(200, study_id=self.session_study.object_id, data_format="json")
        # there are no rows for columns to be in
        self.assertEqual(resp.content, b"[]")
    
    def test_no_data_json_table(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.smart_post_status_code(
            200, study_id=self.session_study.object_id, data_format="json_table"
        )
        # results in a table with a first row of column names
        row = ('[["' + '","'.join(get_table_columns(self.session_study)) + '"]]').encode()
        self.assertEqual(resp.content, row)
    
    def test_one_participant_csv(self):
        resp = self._do_one_participant("csv")
        # the header row and a row of data
        # b'Created On,Patient ID,Status,OS Type,Last Upload,Last Survey Download,Last Registration,Last Set Password,Last Push Token Update,Last Device Settings Update,Last OS Version,App Version Code,App Version Name,Last Heartbeat
        #2024-06-06,patient1,Inactive,ANDROID,None,None,None,None,None,None,None,None,None,None
        row1 = ",".join(get_table_columns(self.session_study)) + "\r\n"
        row2 = "2020-01-01,patient1,Inactive,ANDROID,"
        row2 += "None,None,None,None,None,None,None,None,None,None\r\n"
        self.assertEqual(resp.content, (row1 + row2).encode())
        self.modify_participant()
        row2_2 = "2020-01-01,patient1,Inactive,ANDROID,"
        row2_2 += "2020-01-02 12:00:00 (UTC),2020-01-03 12:00:00 (UTC),2020-01-04 12:00:00 (UTC),"
        row2_2 += "2020-01-05 12:00:00 (UTC),2020-01-06 12:00:00 (UTC),2020-01-07 12:00:00 (UTC),"
        row2_2 += "1.0,6,six,2020-01-08 12:00:00 (UTC)\r\n"
        resp = self._do_one_participant("csv")
        self.assertEqual(resp.content, (row1 + row2_2).encode())
    
    def test_one_participant_json(self):
        resp = self._do_one_participant("json")
        keys = get_table_columns(self.session_study)
        
        row = {
            keys[0]: "2020-01-01",
            keys[1]: "patient1",
            keys[2]: "Inactive",
            keys[3]: "ANDROID",
            keys[4]: "None",
            keys[5]: "None",
            keys[6]: "None",
            keys[7]: "None",
            keys[8]: "None",
            keys[9]: "None",
            keys[10]: "None",
            keys[11]: "None",
            keys[12]: "None",
            keys[13]: "None",
        }
        self.assertEqual(orjson.loads(resp.content), [row])
        
        self.modify_participant()
        resp = self._do_one_participant("json")
        row = {
            keys[0]: "2020-01-01",
            keys[1]: "patient1",
            keys[2]: "Inactive",
            keys[3]: "ANDROID",
            keys[4]: "2020-01-02 12:00:00 (UTC)",
            keys[5]: "2020-01-03 12:00:00 (UTC)",
            keys[6]: "2020-01-04 12:00:00 (UTC)",
            keys[7]: "2020-01-05 12:00:00 (UTC)",
            keys[8]: "2020-01-06 12:00:00 (UTC)",
            keys[9]: "2020-01-07 12:00:00 (UTC)",
            keys[10]: "1.0",
            keys[11]: "6",
            keys[12]: "six",
            keys[13]: "2020-01-08 12:00:00 (UTC)",
        }
        self.assertEqual(orjson.loads(resp.content), [row])
    
    def test_one_participant_json_table(self):
        resp = self._do_one_participant("json_table")
        keys = get_table_columns(self.session_study)
        
        row = [
            "2020-01-01",
            "patient1",
            "Inactive",
            "ANDROID",
            "None",
            "None",
            "None",
            "None",
            "None",
            "None",
            "None",
            "None",
            "None",
            "None",
        ]
        self.assertEqual(orjson.loads(resp.content), [keys, row])
        
        self.modify_participant()
        resp = self._do_one_participant("json_table")
        row = [
            "2020-01-01",
            "patient1",
            "Inactive",
            "ANDROID",
            "2020-01-02 12:00:00 (UTC)",
            "2020-01-03 12:00:00 (UTC)",
            "2020-01-04 12:00:00 (UTC)",
            "2020-01-05 12:00:00 (UTC)",
            "2020-01-06 12:00:00 (UTC)",
            "2020-01-07 12:00:00 (UTC)",
            "1.0",
            "6",
            "six",
            "2020-01-08 12:00:00 (UTC)",
        ]
        self.assertEqual(orjson.loads(resp.content), [keys, row])
    
    def _do_one_participant(self, data_format: str):
        if not hasattr(self, "_default_study_relation"):
            self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        self.default_participant.update_only(created_on=datetime(2020, 1, 1, 12, tzinfo=UTC))
        return self.smart_post_status_code(200, study_id=self.session_study.object_id, data_format=data_format)
    
    def modify_participant(self):
        # you have to update this list if you add fields to EXTRA_TABLE_FIELDS
        some_column_names_and_values = [
            ("created_on", datetime(2020, 1, 1, 12, tzinfo=UTC)),  # not an extra row
            ("last_upload", datetime(2020, 1, 2, 12, tzinfo=UTC)),
            ("last_get_latest_surveys", datetime(2020, 1, 3, 12, tzinfo=UTC)),
            ("last_register_user", datetime(2020, 1, 4, 12, tzinfo=UTC)),
            ("last_set_password", datetime(2020, 1, 5, 12, tzinfo=UTC)),
            ("last_set_fcm_token", datetime(2020, 1, 6, 12, tzinfo=UTC)),
            ("last_get_latest_device_settings", datetime(2020, 1, 7, 12, tzinfo=UTC)),
            ("last_os_version", "1.0"),
            ("last_version_code", "6"),
            ("last_version_name", "six"),
            ("last_heartbeat_checkin", datetime(2020, 1, 8, 12, tzinfo=UTC)),
        ]
        for name, value in some_column_names_and_values:
            setattr(self.default_participant, name, value)
        self.default_participant.save()


class TestGetParticipantUploadHistory(DataApiTest):
    ENDPOINT_NAME = "other_data_apis.get_participant_upload_history"
    
    def create_an_upload(self):
        # file name has a transformation applied to it, the patient id is stripped
        UploadTracking.objects.create(
            participant=self.default_participant,
            file_path=f"{self.default_participant.patient_id}/some_file_name",
            file_size="10",
            timestamp=datetime(2020,1,1,12, tzinfo=UTC),
        )
    
    def test_no_participant_parameter(self):
        # it should 400
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        resp = self.smart_post_status_code(400)
        self.assertEqual(resp.content, b"")
    
    def test_bad_participant_parameter(self):
        # it should 404 and not render the 404 page
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        resp = self.smart_post_status_code(404, participant_id="a" * 8)
        self.assertEqual(resp.content, b"")
    
    def test_researcher_one_participant_no_uploads(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self._test_one_participant_no_uploads()
    
    def test_study_admin_one_participant_no_uploads(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self._test_one_participant_no_uploads()
    
    def test_site_admin_one_participant_no_uploads(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        self._test_one_participant_no_uploads()
    
    def _test_one_participant_no_uploads(self):
        resp = self.smart_post_status_code(200, participant_id=self.default_participant.patient_id)
        content = b"".join(resp.streaming_content)
        self.assertEqual(content, b'[]')
    
    def test_no_relation_one_participant_no_uploads(self):
        resp = self.smart_post_status_code(403, participant_id=self.default_participant.patient_id)
    
    def test_one_participant_one_upload_values(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        self.create_an_upload()
        resp = self.smart_post_status_code(200, participant_id=self.default_participant.patient_id)
        content = b"".join(resp.streaming_content)
        self.assertEqual(
            content,
            b'[{"file_size":10,"timestamp":"2020-01-01T12:00:00Z","file_name":"some_file_name"}]'
        )
    
    def test_one_participant_one_upload_values_list(self):
        # as values but formatted data lacks keys.
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        self.create_an_upload()
        resp = self.smart_post_status_code(
            200, participant_id=self.default_participant.patient_id, omit_keys="true"
        )
        content = b"".join(resp.streaming_content)
        self.assertEqual(content, b'[[10,"2020-01-01T12:00:00Z","some_file_name"]]')
    
    def test_ten_uploads_values(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        for i in range(10):
            self.create_an_upload()
        resp = self.smart_post_status_code(200, participant_id=self.default_participant.patient_id)
        content = b"".join(resp.streaming_content)
        text = b'{"file_size":10,"timestamp":"2020-01-01T12:00:00Z","file_name":"some_file_name"}'
        for i in range(9):
            text += b',{"file_size":10,"timestamp":"2020-01-01T12:00:00Z","file_name":"some_file_name"}'
        text = b"[" + text + b"]"
        self.assertEqual(content, text)
    
    def test_ten_uploads_values_list(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        for i in range(10):
            self.create_an_upload()
        resp = self.smart_post_status_code(
            200, participant_id=self.default_participant.patient_id, omit_keys="true"
        )
        content = b"".join(resp.streaming_content)
        text = b'[10,"2020-01-01T12:00:00Z","some_file_name"]'
        for i in range(9):
            text += b',[10,"2020-01-01T12:00:00Z","some_file_name"]'
        text = b"[" + text + b"]"
        self.assertEqual(content, text)


class TestParticipantHeartbeatHistory(DataApiTest):
    ENDPOINT_NAME = "other_data_apis.get_participant_heartbeat_history"
    
    def create_a_heartbeat(self):
        AppHeartbeats.objects.create(
            timestamp=datetime(2020,1,1,12, tzinfo=UTC), participant=self.default_participant)
    
    def test_no_participant_parameter(self):
        # it should 400
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        resp = self.smart_post_status_code(400)
        self.assertEqual(resp.content, b"")
    
    def test_bad_participant_parameter(self):
        # it should 404 and not render the 404 page
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        resp = self.smart_post_status_code(404, participant_id="a" * 8)
        self.assertEqual(resp.content, b"")
    
    def test_researcher_one_participant_no_heartbeats(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self._test_one_participant_no_heartbeats()
    
    def test_study_admin_one_participant_no_heartbeats(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self._test_one_participant_no_heartbeats()
    
    def test_site_admin_one_participant_no_heartbeats(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        self._test_one_participant_no_heartbeats()
    
    def _test_one_participant_no_heartbeats(self):
        resp = self.smart_post_status_code(200, participant_id=self.default_participant.patient_id)
        content = b"".join(resp.streaming_content)
        self.assertEqual(content, b'[]')
    
    def test_no_relation_one_participant_no_heartbeats(self):
        resp = self.smart_post_status_code(403, participant_id=self.default_participant.patient_id)
    
    def test_one_participant_one_heartbeat_values(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        self.create_a_heartbeat()
        resp = self.smart_post_status_code(200, participant_id=self.default_participant.patient_id)
        content = b"".join(resp.streaming_content)
        self.assertEqual(content, b'[{"timestamp":"2020-01-01T12:00:00Z"}]')
    
    def test_one_participant_one_heartbeat_values_list(self):
        # as values but formatted data lacks keys.
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        self.create_a_heartbeat()
        resp = self.smart_post_status_code(
            200, participant_id=self.default_participant.patient_id, omit_keys="true"
        )
        content = b"".join(resp.streaming_content)
        self.assertEqual(content, b'["2020-01-01T12:00:00Z"]')
    
    def test_ten_heartbeats_values(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        for i in range(10):
            self.create_a_heartbeat()
        resp = self.smart_post_status_code(200, participant_id=self.default_participant.patient_id)
        content = b"".join(resp.streaming_content)
        text = b'{"timestamp":"2020-01-01T12:00:00Z"}'
        for i in range(9):
            text += b',{"timestamp":"2020-01-01T12:00:00Z"}'
        text = b"[" + text + b"]"
        self.assertEqual(content, text)
    
    def test_ten_heartbeats_values_list(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        for i in range(10):
            self.create_a_heartbeat()
        resp = self.smart_post_status_code(
            200, participant_id=self.default_participant.patient_id, omit_keys="true"
        )
        content = b"".join(resp.streaming_content)
        text = b'"2020-01-01T12:00:00Z"'
        for i in range(9):
            text += b',"2020-01-01T12:00:00Z"'
        text = b"[" + text + b"]"
        self.assertEqual(content, text)


class TestParticipantVersionHistory(DataApiTest):
    ENDPOINT_NAME = "other_data_apis.get_participant_version_history"
    
    def create_a_version(self):
        self.default_participant.app_version_history.create(
            app_version_code="1", app_version_name="1.0", os_version="1.0"
        )
    
    def test_no_participant_parameter(self):
        # it should 400
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        resp = self.smart_post_status_code(400)
        self.assertEqual(resp.content, b"")
    
    def test_bad_participant_parameter(self):
        # it should 404 and not render the 404 page
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        resp = self.smart_post_status_code(404, participant_id="a" * 8)
        self.assertEqual(resp.content, b"")
    
    def test_researcher_one_participant_no_versions(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self._test_one_participant_no_versions()
    
    def test_study_admin_one_participant_no_versions(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self._test_one_participant_no_versions()
    
    def test_site_admin_one_participant_no_versions(self):
        self.set_session_study_relation(ResearcherRole.site_admin)
        self._test_one_participant_no_versions()
    
    def _test_one_participant_no_versions(self):
        resp = self.smart_post_status_code(200, participant_id=self.default_participant.patient_id)
        content = b"".join(resp.streaming_content)
        self.assertEqual(content, b'[]')
    
    def test_no_relation_one_participant_no_versions(self):
        resp = self.smart_post_status_code(403, participant_id=self.default_participant.patient_id)
    
    def test_one_participant_one_version_values(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        self.create_a_version()
        resp = self.smart_post_status_code(200, participant_id=self.default_participant.patient_id)
        content = b"".join(resp.streaming_content)
        self.assertEqual(
            content, b'[{"app_version_code":"1","app_version_name":"1.0","os_version":"1.0"}]'
        )
    
    def test_one_participant_one_version_values_list(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        self.create_a_version()
        resp = self.smart_post_status_code(
            200, participant_id=self.default_participant.patient_id, omit_keys="true"
        )
        content = b"".join(resp.streaming_content)
        self.assertEqual(content, b'[["1","1.0","1.0"]]')
    
    def test_ten_versions_values(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        for i in range(10):
            self.create_a_version()
        resp = self.smart_post_status_code(200, participant_id=self.default_participant.patient_id)
        content = b"".join(resp.streaming_content)
        text = b'{"app_version_code":"1","app_version_name":"1.0","os_version":"1.0"}'
        for i in range(9):
            text += b',{"app_version_code":"1","app_version_name":"1.0","os_version":"1.0"}'
        text = b"[" + text + b"]"
        self.assertEqual(content, text)
    
    def test_ten_versions_values_list(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant
        for i in range(10):
            self.create_a_version()
        resp = self.smart_post_status_code(
            200, participant_id=self.default_participant.patient_id, omit_keys="true"
        )
        content = b"".join(resp.streaming_content)
        text = b'["1","1.0","1.0"]'
        for i in range(9):
            text += b',["1","1.0","1.0"]'
        text = b"[" + text + b"]"
        self.assertEqual(content, text)


# other_data_apis.get_summary_statistics is identical to the tableau_api.get_tableau_daily, which is
# tested extensively in test_tableau_api.py. The difference is that this endpoint uses the data
# access api decorator for authentication and the other is explicitly for tableau integration.
# All we need to test is that this works at all.
class TestGetSummaryStatistics(DataApiTest):
    ENDPOINT_NAME = "other_data_apis.get_summary_statistics"
    
    def test_no_study_param(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.smart_post_status_code(400)
    
    def test_no_data(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.smart_post_status_code(200, study_id=self.session_study.object_id)
        content = b"".join(resp.streaming_content)
        self.assertEqual(content, b"[]")
    
    def test_single_summary_statistic(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_summary_statistic_daily
        resp = self.smart_post_status_code(200, study_id=self.session_study.object_id)
        content = b"".join(resp.streaming_content)
        
        # get the data
        list_of_dict = orjson.loads(content)
        self.assertEqual(len(list_of_dict), 1)
        exported_summary_statistic = list_of_dict[0]
        
        # assemble the correct data directly out of the database, do some formatting, confirm match.
        correct = {
            k:v for k,v in 
            self.default_summary_statistic_daily.as_dict().items()
            if k in SERIALIZABLE_FIELD_NAMES
        }
        correct["date"] = correct["date"].isoformat()
        correct["study_id"] = self.session_study.object_id
        correct["participant_id"] = self.default_participant.patient_id
        
        self.assertDictEqual(exported_summary_statistic, correct)
