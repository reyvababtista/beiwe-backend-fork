import json
from datetime import date, datetime, timedelta
from io import BytesIO
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.http.response import FileResponse, HttpResponseRedirect
from django.utils import timezone

from constants.common_constants import API_DATE_FORMAT
from constants.data_stream_constants import ALL_DATA_STREAMS, SURVEY_TIMINGS
from constants.message_strings import (DEVICE_HAS_NO_REGISTERED_TOKEN, MESSAGE_SEND_FAILED_UNKNOWN,
    MESSAGE_SEND_SUCCESS, NO_DELETION_PERMISSION, PARTICIPANT_LOCKED,
    PASSWORD_RESET_FAIL_SITE_ADMIN, PUSH_NOTIFICATIONS_NOT_CONFIGURED)
from constants.user_constants import IOS_API, ResearcherRole
from database.data_access_models import ChunkRegistry
from database.profiling_models import DataAccessRecord
from database.schedule_models import ArchivedEvent, Intervention, ScheduledEvent
from database.security_models import ApiKey
from database.study_models import Study, StudyField
from database.survey_models import Survey
from database.user_models_participant import (Participant, ParticipantDeletionEvent,
    ParticipantFCMHistory)
from database.user_models_researcher import Researcher, StudyRelation
from libs.copy_study import format_study
from tests.common import CommonTestCase, DataApiTest, ParticipantSessionTest, ResearcherSessionTest
from tests.helpers import DummyThreadPool


#
## data_access_web_form
#
class TestDataAccessWebFormPage(ResearcherSessionTest):
    ENDPOINT_NAME = "data_access_web_form.data_api_web_form_page"
    
    def test(self):
        resp = self.smart_get()
        self.assert_present("Reset Data-Download API Access Credentials", resp.content)
        id_key, secret_key = self.session_researcher.reset_access_credentials()
        resp = self.smart_get()
        self.assert_not_present("Reset Data-Download API Access Credentials", resp.content)

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
        ApiKey.generate(researcher=r2, has_tableau_api_permissions=True, readable_name="test_api_key")
        relation_id = self.generate_study_relation(r2, self.default_study, ResearcherRole.researcher).id
        record = DataAccessRecord.objects.create(researcher=r2, query_params="test_junk", username=r2.username)
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
        self.assertTrue(
            r2.check_password(r2.username, self.DEFAULT_RESEARCHER_PASSWORD + "1")
        )
        self.assertFalse(
            r2.check_password(r2.username, self.DEFAULT_RESEARCHER_PASSWORD)
        )
        self.assertEqual(r2.web_sessions.count(), 0)
    
    def _test_cannot_change(self, r2: Researcher, message: str = None):
        ret = self.smart_post(
            researcher_id=r2.id,
            password=self.DEFAULT_RESEARCHER_PASSWORD + "1",
        )
        if message:
            content = self.easy_get("system_admin_pages.edit_researcher", researcher_pk=r2.id).content
            self.assert_present(message, content)
        r2.refresh_from_db()
        self.assertFalse(r2.password_force_reset)
        self.assertFalse(
            r2.check_password(r2.username, self.DEFAULT_RESEARCHER_PASSWORD + "1")
        )
        self.assertTrue(
            r2.check_password(r2.username, self.DEFAULT_RESEARCHER_PASSWORD)
        )
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

#
## study_api
#

# FIXME: implement this test beyond "it doesn't crash"
class TestStudyParticipantApi(ResearcherSessionTest):
    ENDPOINT_NAME = "study_api.study_participants_api"
    
    COLUMN_ORDER_KEY = "order[0][column]"
    ORDER_DIRECTION_KEY = "order[0][dir]"
    SEARCH_PARAMETER = "search[value]"
    SOME_TIMESTAMP = timezone.make_aware(datetime(2020, 10, 1))
    
    THE_STATUS_FIELD_NAMES = [
        "last_get_latest_surveys",
        "last_upload",
        "last_register_user",
        "last_set_password",
        "last_set_fcm_token",
        "last_get_latest_device_settings",
    ]
    
    # This endpoint is stupidly complex, it implements pagination, sorting, search ordering.
    
    def setUp(self) -> None:
        # we need a flag for multiple calls to set_session_study_relation
        ret = super().setUp()
        self.STUDY_RELATION_SET = False
        return ret
    
    @property
    def DEFAULT_PARAMETERS(self):
        # you need to be at least a researcher, factor out this clutter
        if not self.STUDY_RELATION_SET:
            self.set_session_study_relation(ResearcherRole.researcher)
            self.STUDY_RELATION_SET = True
        return {
            "draw": 1,
            "start": 0,
            "length": 10,
            # sort, sort order, search term.  order key is index into this list, larger values
            # target first interventions then custom fields:
            # ['created_on', 'patient_id', 'registered', 'os_type']
            self.COLUMN_ORDER_KEY: 0,
            self.ORDER_DIRECTION_KEY: "asc",
            self.SEARCH_PARAMETER: "",
        }
    
    def CONSTRUCT_RESPONSE(self, status: str):
        return {
            "draw": 1,
            "recordsTotal": 1,
            "recordsFiltered": 1,
            "data": [[self.SOME_TIMESTAMP.strftime(API_DATE_FORMAT),
                      self.default_participant.patient_id,
                      status,
                      "ANDROID"]]
        }
    
    def test_basics(self):
        # manually set the created on timestamp... its a pain to set and a pain to test.
        self.default_participant.update_only(created_on=self.SOME_TIMESTAMP)
        # this endpoint uses get args, for which we have to pass in the dict as the "data" kwarg
        resp = self.smart_post_status_code(200, self.session_study.id, **self.DEFAULT_PARAMETERS)
        content = json.loads(resp.content.decode())
        # this participant has never contacted the server, but it does have a device id.
        self.assertEqual(content, self.CONSTRUCT_RESPONSE("Inactive"))
    
    def test_various_statuses(self):
        # this test tests all the timestamp fields that are used to determine the status of a participant,
        # which is displayed on the status column of the participants table.
        self.default_participant.update_only(created_on=self.SOME_TIMESTAMP)
        
        # That triple **:
        # For every field name - set all of them to null, but override the first dict ** with a
        # second dict ** that forces the status_field_name to the current/appropriate time. (You
        # can't ** two dicts with overlapping keys as function parameters directly, you get a
        # "multiple values for keyword argument" error - which is a TypeError for some reason), but
        # you Can that into an inline dictionary, and then ** that dictionary into the function
        # parameters.
        fields_as_nones = {field: None for field in self.THE_STATUS_FIELD_NAMES}
        t = timezone.now()
        for status_field_name in self.THE_STATUS_FIELD_NAMES:
            self.default_participant.update_only(**{**fields_as_nones, **{status_field_name: t}})
            resp = self.smart_post_status_code(200, self.session_study.id, **self.DEFAULT_PARAMETERS)
            self.assertDictEqual(json.loads(resp.content), self.CONSTRUCT_RESPONSE("Active (just now)"))
        
        t = timezone.now() - timedelta(minutes=6)
        for status_field_name in self.THE_STATUS_FIELD_NAMES:
            self.default_participant.update_only(**{**fields_as_nones, **{status_field_name: t}})
            resp = self.smart_post_status_code(200, self.session_study.id, **self.DEFAULT_PARAMETERS)
            self.assertDictEqual(json.loads(resp.content), self.CONSTRUCT_RESPONSE("Active (last hour)"))
        
        t = timezone.now() - timedelta(hours=2)
        for status_field_name in self.THE_STATUS_FIELD_NAMES:
            self.default_participant.update_only(**{**fields_as_nones, **{status_field_name: t}})
            resp = self.smart_post_status_code(200, self.session_study.id, **self.DEFAULT_PARAMETERS)
            self.assertDictEqual(json.loads(resp.content), self.CONSTRUCT_RESPONSE("Active (past day)"))
        
        t = timezone.now() - timedelta(days=2)
        for status_field_name in self.THE_STATUS_FIELD_NAMES:
            self.default_participant.update_only(**{**fields_as_nones, **{status_field_name: t}})
            resp = self.smart_post_status_code(200, self.session_study.id, **self.DEFAULT_PARAMETERS)
            self.assertDictEqual(json.loads(resp.content), self.CONSTRUCT_RESPONSE("Active (past week)"))
    
    def test_with_intervention(self):
        self.default_participant.update_only(created_on=self.SOME_TIMESTAMP)
        # need to populate some database state, this database stat is expected to be populated when
        # a participant is created and/or when an intervention is created.
        self.default_intervention
        self.default_populated_intervention_date
        resp = self.smart_post_status_code(200, self.session_study.id, **self.DEFAULT_PARAMETERS)
        content = json.loads(resp.content.decode())
        correct_content = self.CONSTRUCT_RESPONSE("Inactive")
        correct_content["data"][0].append(self.CURRENT_DATE.strftime(API_DATE_FORMAT))  # the value populated in the intervention date
        self.assertEqual(content, correct_content)
    
    def test_with_custom_field(self):
        self.default_participant.update_only(created_on=self.SOME_TIMESTAMP)
        self.default_participant_field_value  # populate database state
        resp = self.smart_post_status_code(200, self.session_study.id, **self.DEFAULT_PARAMETERS)
        content = json.loads(resp.content.decode())
        correct_content = self.CONSTRUCT_RESPONSE("Inactive")
        correct_content["data"][0].append(self.DEFAULT_PARTICIPANT_FIELD_VALUE)  # default value
        self.assertEqual(content, correct_content)
    
    def test_with_both(self):
        self.default_participant.update_only(created_on=self.SOME_TIMESTAMP)
        self.default_intervention  # populate database state
        self.default_populated_intervention_date
        self.default_participant_field_value
        resp = self.smart_post_status_code(200, self.session_study.id, **self.DEFAULT_PARAMETERS)
        content = json.loads(resp.content.decode())
        correct_content = self.CONSTRUCT_RESPONSE("Inactive")
        correct_content["data"][0].append(self.CURRENT_DATE.strftime(API_DATE_FORMAT))
        correct_content["data"][0].append(self.DEFAULT_PARTICIPANT_FIELD_VALUE)
        self.assertEqual(content, correct_content)
    
    def test_simple_ordering(self):
        # setup default participant
        self.default_participant.update_only(created_on=self.SOME_TIMESTAMP)
        self.default_intervention
        self.default_populated_intervention_date
        self.default_participant_field_value
        # setup second participant
        p2 = self.generate_participant(self.session_study, "patient2")
        p2.update_only(created_on=self.SOME_TIMESTAMP + timedelta(days=1))  # for sorting
        self.generate_intervention_date(p2, self.default_intervention, None)  # correct db population
        # construct the correct response data (yuck)
        correct_content = self.CONSTRUCT_RESPONSE("Inactive")
        correct_content["recordsTotal"] = 2
        correct_content["recordsFiltered"] = 2
        correct_content["data"][0].append(self.CURRENT_DATE.strftime(API_DATE_FORMAT))
        correct_content["data"][0].append(self.DEFAULT_PARTICIPANT_FIELD_VALUE)
        # created on, patient id, registered, os_type, intervention date, custom field
        # (registered is based on presence of os_type)
        correct_content["data"].append([
            p2.created_on.strftime(API_DATE_FORMAT), p2.patient_id, "Inactive", "ANDROID", "", ""
        ])
        # request, compare
        params = self.DEFAULT_PARAMETERS
        resp = self.smart_post_status_code(200, self.session_study.id, **params)
        content = json.loads(resp.content.decode())
        self.assertEqual(content, correct_content)
        # reverse the order
        params[self.ORDER_DIRECTION_KEY] = "desc"
        correct_content["data"].append(correct_content["data"].pop(0))  # swap 2 rows
        resp = self.smart_post_status_code(200, self.session_study.id, **params)
        content = json.loads(resp.content.decode())
        self.assertEqual(content, correct_content)


class TestInterventionsPage(ResearcherSessionTest):
    ENDPOINT_NAME = "study_api.interventions_page"
    REDIRECT_ENDPOINT_NAME = "study_api.interventions_page"
    
    def test_get(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self.generate_intervention(self.session_study, "obscure_name_of_intervention")
        resp = self.smart_get(self.session_study.id)
        self.assert_present("obscure_name_of_intervention", resp.content)
    
    def test_post(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        resp = self.smart_post(self.session_study.id, new_intervention="ohello")
        self.assertEqual(resp.status_code, 302)
        intervention = Intervention.objects.get(study=self.session_study)
        self.assertEqual(intervention.name, "ohello")


class TestDeleteIntervention(ResearcherSessionTest):
    ENDPOINT_NAME = "study_api.delete_intervention"
    REDIRECT_ENDPOINT_NAME = "study_api.interventions_page"
    
    def test(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        intervention = self.generate_intervention(self.session_study, "obscure_name_of_intervention")
        self.smart_post_redirect(self.session_study.id, intervention=intervention.id)
        self.assertFalse(Intervention.objects.filter(id=intervention.id).exists())


class TestEditIntervention(ResearcherSessionTest):
    ENDPOINT_NAME = "study_api.edit_intervention"
    REDIRECT_ENDPOINT_NAME = "study_api.interventions_page"
    
    def test(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        intervention = self.generate_intervention(self.session_study, "obscure_name_of_intervention")
        self.smart_post_redirect(
            self.session_study.id, intervention_id=intervention.id, edit_intervention="new_name"
        )
        intervention_new = Intervention.objects.get(id=intervention.id)
        self.assertEqual(intervention.id, intervention_new.id)
        self.assertEqual(intervention_new.name, "new_name")


class TestStudyFields(ResearcherSessionTest):
    ENDPOINT_NAME = "study_api.study_fields"
    REDIRECT_ENDPOINT_NAME = "study_api.study_fields"
    
    def test_get(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self.generate_study_field(self.session_study, "obscure_name_of_study_field")
        # This isn't a pure redirect endpoint, we need get to have a 200
        resp = self.smart_get(self.session_study.id)
        self.assertEqual(resp.status_code, 200)
        self.assert_present("obscure_name_of_study_field", resp.content)
    
    def test_post(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        resp = self.smart_post_redirect(self.session_study.id, new_field="ohello")
        self.assertEqual(resp.status_code, 302)
        study_field = StudyField.objects.get(study=self.session_study)
        self.assertEqual(study_field.field_name, "ohello")


class TestDeleteStudyField(ResearcherSessionTest):
    ENDPOINT_NAME = "study_api.delete_field"
    REDIRECT_ENDPOINT_NAME = "study_api.study_fields"
    
    def test(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        study_field = self.generate_study_field(self.session_study, "obscure_name_of_study_field")
        self.smart_post_redirect(self.session_study.id, field=study_field.id)
        self.assertFalse(StudyField.objects.filter(id=study_field.id).exists())


class TestEditStudyField(ResearcherSessionTest):
    ENDPOINT_NAME = "study_api.edit_custom_field"
    REDIRECT_ENDPOINT_NAME = "study_api.study_fields"
    
    def test(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        study_field = self.generate_study_field(self.session_study, "obscure_name_of_study_field")
        self.smart_post_redirect(
            self.session_study.id, field_id=study_field.id, edit_custom_field="new_name"
        )
        study_field_new = StudyField.objects.get(id=study_field.id)
        self.assertEqual(study_field.id, study_field_new.id)
        self.assertEqual(study_field_new.field_name, "new_name")

#
## participant_pages
#

# FIXME: implement more tests of this endpoint, it is complex.
class TestNotificationHistory(ResearcherSessionTest):
    ENDPOINT_NAME = "participant_pages.notification_history"
    
    def test(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        self.generate_archived_event(self.default_survey, self.default_participant)
        self.smart_get_status_code(200, self.session_study.id, self.default_participant.patient_id)


class TestParticipantPage(ResearcherSessionTest):
    ENDPOINT_NAME = "participant_pages.participant_page"
    REDIRECT_ENDPOINT_NAME = "participant_pages.participant_page"
    
    def test_get(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        # This isn't a pure redirect endpoint, we need to test for a 200
        self.easy_get(
            self.ENDPOINT_NAME, status_code=200,
            study_id=self.session_study.id, patient_id=self.default_participant.patient_id)
    
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
        self.smart_post_redirect(self.session_study.id, self.default_participant.patient_id,
            **{post_param_name: "any string value"})
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
        self.smart_post_redirect(self.session_study.id, self.default_participant.patient_id,
            **{post_param_name: "2020-01-01"})
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
        self.smart_post_redirect(self.session_study.id, self.default_participant.patient_id,
            **{post_param_name: date_string})
        intervention_date.refresh_from_db()
        self.assertEqual(intervention_date.date, None)
        page = self.easy_get(
            self.ENDPOINT_NAME, status_code=200,
            study_id=self.session_study.id, patient_id=self.default_participant.patient_id).content
        self.assert_present(
            'Invalid date format, please use the date selector or YYYY-MM-DD.', page
        )

#
## copy_study_api
#

# FIXME: add interventions and surveys to the export tests
class TestExportStudySettingsFile(ResearcherSessionTest):
    ENDPOINT_NAME = "copy_study_api.export_study_settings_file"
    
    def test(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        # FileResponse objects stream, which means you need to iterate over `resp.streaming_content``
        resp: FileResponse = self.smart_get(self.session_study.id)
        # sanity check...
        items_to_iterate = 0
        for file_bytes in resp.streaming_content:
            items_to_iterate += 1
        self.assertEqual(items_to_iterate, 1)
        # get survey, check device_settings, surveys, interventions are all present
        output_survey: dict = json.loads(file_bytes.decode())  # make sure it is a json file
        self.assertIn("device_settings", output_survey)
        self.assertIn("surveys", output_survey)
        self.assertIn("interventions", output_survey)
        output_device_settings: dict = output_survey["device_settings"]
        real_device_settings = self.session_device_settings.export()
        # confirm that all elements are equal for the dicts
        for k, v in output_device_settings.items():
            self.assertEqual(v, real_device_settings[k])


# FIXME: add interventions and surveys to the import tests
class TestImportStudySettingsFile(ResearcherSessionTest):
    ENDPOINT_NAME = "copy_study_api.import_study_settings_file"
    REDIRECT_ENDPOINT_NAME = "system_admin_pages.edit_study"
    
    # other post params: device_settings, surveys
    
    def test_no_device_settings_no_surveys(self):
        content = self._test(False, False)
        self.assert_present("Did not alter", content)
        self.assert_present("Copied 0 Surveys and 0 Audio Surveys", content)
    
    def test_device_settings_no_surveys(self):
        content = self._test(True, False)
        self.assert_present("Settings with custom values.", content)
        self.assert_present("Copied 0 Surveys and 0 Audio Surveys", content)
    
    def test_device_settings_and_surveys(self):
        content = self._test(True, True)
        self.assert_present("Settings with custom values.", content)
        self.assert_present("Copied 0 Surveys and 0 Audio Surveys", content)
    
    def test_bad_filename(self):
        content = self._test(True, True, ".exe", success=False)
        # FIXME: this is not present in the html, it should be  - string doesn't appear in codebase...
        # self.assert_present("You can only upload .json files.", content)
    
    def _test(
        self, device_settings: bool, surveys: bool, extension: str = "json", success: bool = True
    ) -> bytes:
        self.set_session_study_relation(ResearcherRole.site_admin)
        study2 = self.generate_study("study_2")
        self.assertEqual(self.session_device_settings.gps, True)
        self.session_device_settings.update(gps=False)
        
        # this is the function that creates the canonical study representation wrapped in a burrito
        survey_json_file = BytesIO(format_study(self.session_study).encode())
        survey_json_file.name = f"something.{extension}"  # ayup, that's how you add a name...
        
        self.smart_post_redirect(
            study2.id,
            upload=survey_json_file,
            device_settings="true" if device_settings else "false",
            surveys="true" if surveys else "false",
        )
        study2.device_settings.refresh_from_db()
        if success:
            self.assertEqual(study2.device_settings.gps, not device_settings)
        # return the page, we always need it
        return self.easy_get(self.REDIRECT_ENDPOINT_NAME, status_code=200, study_id=study2.id).content


#
## survey_api
#

class TestICreateSurvey(ResearcherSessionTest):
    ENDPOINT_NAME = "survey_api.create_survey"
    REDIRECT_ENDPOINT_NAME = "survey_designer.render_edit_survey"
    
    def test_tracking(self):
        self._test(Survey.TRACKING_SURVEY)
    
    def test_audio(self):
        self._test(Survey.AUDIO_SURVEY)
    
    def test_image(self):
        self._test(Survey.IMAGE_SURVEY)
    
    def _test(self, survey_type: str):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.assertEqual(Survey.objects.count(), 0)
        resp = self.smart_get_redirect(self.session_study.id, survey_type)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Survey.objects.count(), 1)
        survey: Survey = Survey.objects.get()
        self.assertEqual(survey_type, survey.survey_type)


# FIXME: add schedule removal tests to this test
class TestDeleteSurvey(ResearcherSessionTest):
    ENDPOINT_NAME = "survey_api.delete_survey"
    REDIRECT_ENDPOINT_NAME = "admin_pages.view_study"
    
    def test(self):
        self.assertEqual(Survey.objects.count(), 0)
        self.set_session_study_relation(ResearcherRole.researcher)
        survey = self.generate_survey(self.session_study, Survey.TRACKING_SURVEY)
        self.assertEqual(Survey.objects.count(), 1)
        self.smart_post_redirect(self.session_study.id, survey.id)
        self.assertEqual(Survey.objects.count(), 1)
        self.assertEqual(Survey.objects.filter(deleted=False).count(), 0)


# FIXME: implement more details of survey object updates
class TestUpdateSurvey(ResearcherSessionTest):
    ENDPOINT_NAME = "survey_api.update_survey"
    
    def test_with_hax_to_bypass_the_hard_bit(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        survey = self.generate_survey(self.session_study, Survey.TRACKING_SURVEY)
        self.assertEqual(survey.settings, '{}')
        resp = self.smart_post(
            self.session_study.id, survey.id, content='[]', settings='[]',
            weekly_timings='[]', absolute_timings='[]', relative_timings='[]',
        )
        survey.refresh_from_db()
        self.assertEqual(survey.settings, '[]')
        self.assertEqual(resp.status_code, 201)


#
## survey_designer
#

# FIXME: add interventions and survey schedules
class TestRenderEditSurvey(ResearcherSessionTest):
    ENDPOINT_NAME = "survey_designer.render_edit_survey"
    
    def test(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        survey = self.generate_survey(self.session_study, Survey.TRACKING_SURVEY)
        self.smart_get_status_code(200, self.session_study.id, survey.id)


#
## participant_administration
#

class TestDeleteParticipant(ResearcherSessionTest):
    ENDPOINT_NAME = "participant_administration.delete_participant"
    REDIRECT_ENDPOINT_NAME = "participant_pages.participant_page"
    
    # most of this was copy-pasted from TestUnregisterParticipant, which was copied from TestResetDevice
    
    def test_bad_study_id(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.smart_post(patient_id=self.default_participant.patient_id, study_id=0)
        self.assertEqual(resp.status_code, 404)
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.is_dead, False)
    
    def test_wrong_study_id(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        study2 = self.generate_study("study2")
        self.generate_study_relation(self.session_researcher, study2, ResearcherRole.researcher)
        self.smart_post_redirect(patient_id=self.default_participant.patient_id, study_id=study2.id)
        self.assert_present(
            "is not in study",
            self.redirect_get_contents(patient_id=self.default_participant.patient_id, study_id=study2.id)
        )
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.is_dead, False)
    
    def test_bad_participant(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.smart_post_redirect(patient_id="invalid", study_id=self.session_study.id)
        self.assert_present(
            "does not exist",
            self.easy_get("admin_pages.view_study", status_code=200, study_id=self.session_study.id).content
        )
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.is_dead, False)
    
    def test_participant_already_queued(self):
        ParticipantDeletionEvent.objects.create(participant=self.default_participant)
        self.set_session_study_relation(ResearcherRole.researcher)
        self.smart_post_redirect(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        page = self.redirect_get_contents(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        self.assert_present(
            PARTICIPANT_LOCKED.format(patient_id=self.default_participant.patient_id), page
        )
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.is_dead, True)
        self.assertEqual(self.default_participant.has_deletion_event, True)
        self.assertEqual(self.default_participant.deleted, False)
        self.assertEqual(ParticipantDeletionEvent.objects.count(), 1)
    
    def test_success(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self._test_success()
    
    def _test_success(self):
        self.assertEqual(self.default_participant.is_dead, False)
        self.assertEqual(self.default_participant.has_deletion_event, False)
        self.assertEqual(self.default_participant.deleted, False)
        self.assertEqual(ParticipantDeletionEvent.objects.count(), 0)
        
        self.smart_post_redirect(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        page = self.redirect_get_contents(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.is_dead, True)
        self.assertEqual(self.default_participant.has_deletion_event, True)
        self.assertEqual(self.default_participant.deleted, False)
        self.assertEqual(ParticipantDeletionEvent.objects.count(), 1)
        self.assert_present(
            PARTICIPANT_LOCKED.format(patient_id=self.default_participant.patient_id), page
        )
        self.assert_present(  # assert page component isn't present
            "This action deletes all data that this participant has ever uploaded", page
        )
    
    # look the feature works and these tests are overkill, okay?
    def test_relation_restriction_researcher(self):
        p1, p2 = self.get_patches([ResearcherRole.study_admin])
        with p1, p2:
            self.set_session_study_relation(ResearcherRole.researcher)
            self._test_relation_restriction_failure()
    
    def test_relation_restriction_site_admin(self):
        p1, p2 = self.get_patches([ResearcherRole.site_admin])
        with p1, p2:
            self.set_session_study_relation(ResearcherRole.study_admin)
            self._test_relation_restriction_failure()
    
    def test_relation_restriction_site_admin_works_just_site_admins(self):
        p1, p2 = self.get_patches([ResearcherRole.site_admin])
        with p1, p2:
            self.set_session_study_relation(ResearcherRole.site_admin)
            self._test_success()
    
    def test_relation_restriction_site_admin_works_researcher(self):
        p1, p2 = self.get_patches([ResearcherRole.study_admin, ResearcherRole.researcher])
        with p1, p2:
            self.set_session_study_relation(ResearcherRole.site_admin)
            self._test_success()
    
    def test_relation_restriction_site_admin_works_study_admin(self):
        p1, p2 = self.get_patches([ResearcherRole.study_admin, ResearcherRole.researcher])
        with p1, p2:
            self.set_session_study_relation(ResearcherRole.site_admin)
            self._test_success()
    
    def test_relation_restriction_study_admin_works_researcher(self):
        p1, p2 = self.get_patches([ResearcherRole.study_admin, ResearcherRole.researcher])
        with p1, p2:
            self.set_session_study_relation(ResearcherRole.study_admin)
            self._test_success()
    
    def get_patches(self, the_patch):
        from api import participant_administration
        from pages import participant_pages
        return (
            patch.object(participant_pages, "DATA_DELETION_ALLOWED_RELATIONS", the_patch),
            patch.object(participant_administration, "DATA_DELETION_ALLOWED_RELATIONS", the_patch),
        )
    
    def _test_relation_restriction_failure(self):
        self.smart_post_redirect(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        page = self.redirect_get_contents(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        self.assert_not_present(  # assert page component isn't present
            "This action deletes all data that this participant has ever uploaded", page
        )
        self.assert_not_present(  # assert normal error Didn't happen
            PARTICIPANT_LOCKED.format(patient_id=self.default_participant.patient_id), page
        )
        self.assert_present(  # assert specific error Did happen
            NO_DELETION_PERMISSION.format(patient_id=self.default_participant.patient_id), page
        )
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.is_dead, False)
        self.assertEqual(self.default_participant.has_deletion_event, False)
        self.assertEqual(self.default_participant.deleted, False)
        self.assertEqual(ParticipantDeletionEvent.objects.count(), 0)
    
    def test_deleted_participant(self):
        # just being clear that the partricipant is not retired.
        self.default_participant.update(permanently_retired=False, deleted=True)
        self.set_session_study_relation(ResearcherRole.researcher)
        self.smart_post_redirect(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        page = self.redirect_get_contents(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        self.assert_present(
            PARTICIPANT_LOCKED.format(patient_id=self.default_participant.patient_id), page
        )
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.is_dead, True)
        self.assertEqual(self.default_participant.has_deletion_event, False)
        self.assertEqual(self.default_participant.deleted, True)
        self.assertEqual(ParticipantDeletionEvent.objects.count(), 0)


# FIXME: this endpoint doesn't validate the researcher on the study
# FIXME: redirect was based on referrer.
class TestResetParticipantPassword(ResearcherSessionTest):
    ENDPOINT_NAME = "participant_administration.reset_participant_password"
    REDIRECT_ENDPOINT_NAME = "participant_pages.participant_page"
    
    def test_success(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        old_password = self.default_participant.password
        self.smart_post_redirect(study_id=self.session_study.id, patient_id=self.default_participant.patient_id)
        self.default_participant.refresh_from_db()
        self.assert_present(
            "password has been reset to",
            self.easy_get("admin_pages.view_study", status_code=200, study_id=self.session_study.id).content
        )
        self.assertNotEqual(self.default_participant.password, old_password)
    
    def test_bad_participant(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.smart_post_redirect(study_id=self.session_study.id, patient_id="why hello")
        self.assertFalse(Participant.objects.filter(patient_id="why hello").exists())
        # self.assert_present("does not exist", self.redirect_get_contents(self.session_study.id))
        self.assert_present(
            "does not exist",
            self.easy_get(
                "admin_pages.view_study", status_code=200, study_id=self.session_study.id
            ).content
        )
    
    def test_bad_study(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        study2 = self.generate_study("study2")
        self.generate_study_relation(self.session_researcher, study2, ResearcherRole.researcher)
        old_password = self.default_participant.password
        self.smart_post_redirect(study_id=study2.id, patient_id=self.default_participant.patient_id)
        self.assert_present(
            "is not in study",
            self.easy_get("admin_pages.view_study", status_code=200, study_id=self.session_study.id).content
        )
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.password, old_password)
    
    def test_deleted_participant(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant.update(deleted=True)
        old_password = self.default_participant.password
        self.smart_post_redirect(study_id=self.session_study.id, patient_id=self.default_participant.patient_id)
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.password, old_password)
        page = self.redirect_get_contents(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        self.assert_present(
            PARTICIPANT_LOCKED.format(patient_id=self.default_participant.patient_id), page
        )


class TestResetDevice(ResearcherSessionTest):
    ENDPOINT_NAME = "participant_administration.clear_device_id"
    REDIRECT_ENDPOINT_NAME = "participant_pages.participant_page"
    
    def test_bad_study_id(self):
        self.default_participant.update(device_id="12345")
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.smart_post(patient_id=self.default_participant.patient_id, study_id=0)
        self.assertEqual(resp.status_code, 404)
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.device_id, "12345")
    
    def test_wrong_study_id(self):
        self.default_participant.update(device_id="12345")
        self.set_session_study_relation(ResearcherRole.researcher)
        study2 = self.generate_study("study2")
        self.generate_study_relation(self.session_researcher, study2, ResearcherRole.researcher)
        self.smart_post_redirect(patient_id=self.default_participant.patient_id, study_id=study2.id)
        self.assert_present(
            "is not in study",
            self.easy_get("admin_pages.view_study", status_code=200, study_id=self.session_study.id).content
        )
        self.assertEqual(Participant.objects.count(), 1)
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.device_id, "12345")
    
    def test_bad_participant(self):
        self.default_participant.update(device_id="12345")
        self.assertEqual(Participant.objects.count(), 1)
        self.set_session_study_relation(ResearcherRole.researcher)
        self.smart_post_redirect(patient_id="invalid", study_id=self.session_study.id)
        self.assert_present(
            "does not exist",
            self.easy_get("admin_pages.view_study", status_code=200, study_id=self.session_study.id).content
        )
        
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.device_id, "12345")
    
    def test_success(self):
        self.default_participant.update(device_id="12345")
        self.set_session_study_relation(ResearcherRole.researcher)
        self.smart_post_redirect(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        self.assert_present(
            "device status has been cleared",
            self.easy_get("admin_pages.view_study", status_code=200, study_id=self.session_study.id).content
        )
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.device_id, "")
    
    def test_deleted_participant(self):
        self.default_participant.update(device_id="12345", deleted=True)
        self.set_session_study_relation(ResearcherRole.researcher)
        self.smart_post_redirect(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        page = self.redirect_get_contents(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        self.assert_present(PARTICIPANT_LOCKED.format(patient_id=self.default_participant.patient_id), page)
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.device_id, "12345")


class TestToggleParticipantEasyEnrollment(ResearcherSessionTest):
    ENDPOINT_NAME = "participant_administration.toggle_easy_enrollment"
    REDIRECT_ENDPOINT_NAME = "participant_pages.participant_page"
    
    def test_admin(self):
        self.assertFalse(self.default_study.easy_enrollment)
        self.set_session_study_relation(ResearcherRole.study_admin)
        self._test_success()
    
    def test_researcher(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self._test_success()
    
    def test_study_easy_enrollment_enabled(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_study.update(easy_enrollment=True)
        self._test_success()
    
    def _test_success(self):
        self.assertFalse(self.default_participant.easy_enrollment)
        self.smart_post_redirect(patient_id=self.default_participant.patient_id, study_id=self.session_study.id)
        self.default_participant.refresh_from_db()
        self.assertTrue(self.default_participant.easy_enrollment)
        self.smart_post_redirect(patient_id=self.default_participant.patient_id, study_id=self.session_study.id)
        self.default_participant.refresh_from_db()
        self.assertFalse(self.default_participant.easy_enrollment)
    
    def test_no_relation(self):
        self.assertFalse(self.default_participant.easy_enrollment)
        resp = self.smart_post(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        self.assertEqual(resp.status_code, 403)
        self.default_participant.refresh_from_db()
        self.assertFalse(self.default_participant.easy_enrollment)
    
    def test_deleted_participant(self):
        self.default_participant.update(deleted=True)
        self.set_session_study_relation(ResearcherRole.researcher)
        self.assertFalse(self.default_participant.easy_enrollment)
        self.smart_post_redirect(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        self.default_participant.refresh_from_db()
        self.assertFalse(self.default_participant.easy_enrollment)
        page = self.redirect_get_contents(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        self.assert_present(PARTICIPANT_LOCKED.format(patient_id=self.default_participant.patient_id), page)


class TestUnregisterParticipant(ResearcherSessionTest):
    ENDPOINT_NAME = "participant_administration.retire_participant"
    REDIRECT_ENDPOINT_NAME = "participant_pages.participant_page"
    # most of this was copy-pasted from TestResetDevice
    
    def test_bad_study_id(self):
        self.assertEqual(self.default_participant.permanently_retired, False)
        self.set_session_study_relation(ResearcherRole.researcher)
        resp = self.smart_post(patient_id=self.default_participant.patient_id, study_id=0)
        self.assertEqual(resp.status_code, 404)
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.permanently_retired, False)
    
    def test_wrong_study_id(self):
        self.assertEqual(self.default_participant.permanently_retired, False)
        self.set_session_study_relation(ResearcherRole.researcher)
        study2 = self.generate_study("study2")
        self.generate_study_relation(self.session_researcher, study2, ResearcherRole.researcher)
        self.smart_post_redirect(patient_id=self.default_participant.patient_id, study_id=study2.id)
        self.assert_present(
            "is not in study",
            self.easy_get("admin_pages.view_study", status_code=200, study_id=self.session_study.id).content
        )
        self.assertEqual(Participant.objects.count(), 1)
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.permanently_retired, False)
    
    def test_bad_participant(self):
        self.assertEqual(self.default_participant.permanently_retired, False)
        self.assertEqual(Participant.objects.count(), 1)
        self.set_session_study_relation(ResearcherRole.researcher)
        self.smart_post_redirect(patient_id="invalid", study_id=self.session_study.id)
        self.assert_present(
            "does not exist",
            self.easy_get("admin_pages.view_study", status_code=200, study_id=self.session_study.id).content
        )
        # self.assert_present("does not exist", self.redirect_get_contents(self.session_study.id))
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.permanently_retired, False)
    
    def test_participant_permanently_retired_true(self):
        self.default_participant.update(permanently_retired=True)
        self.assertEqual(Participant.objects.count(), 1)
        self.set_session_study_relation(ResearcherRole.researcher)
        self.smart_post_redirect(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        self.assert_present(
            "already permanently retired",
            self.easy_get("admin_pages.view_study", status_code=200, study_id=self.session_study.id).content,
        )
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.permanently_retired, True)
    
    def test_success(self):
        self.assertEqual(self.default_participant.permanently_retired, False)
        self.set_session_study_relation(ResearcherRole.researcher)
        self.smart_post_redirect(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        self.assert_present(
            "was successfully retired from the study",
            self.easy_get("admin_pages.view_study", status_code=200, study_id=self.session_study.id).content
        )
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.permanently_retired, True)
    
    def test_deleted_participant(self):
        self.assertEqual(self.default_participant.permanently_retired, False)
        self.default_participant.update(deleted=True)
        self.set_session_study_relation(ResearcherRole.researcher)
        self.smart_post_redirect(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.permanently_retired, False)
        page = self.redirect_get_contents(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        self.assert_present(
            PARTICIPANT_LOCKED.format(patient_id=self.default_participant.patient_id), page
        )



# FIXME: test extended database effects of generating participants
class CreateNewParticipant(ResearcherSessionTest):
    ENDPOINT_NAME = "participant_administration.create_new_participant"
    REDIRECT_ENDPOINT_NAME = "admin_pages.view_study"
    
    @patch("api.participant_administration.s3_upload")
    @patch("api.participant_administration.create_client_key_pair")
    def test(self, create_client_keypair: MagicMock, s3_upload: MagicMock):
        # this test does not make calls to S3
        self.set_session_study_relation(ResearcherRole.researcher)
        self.assertFalse(Participant.objects.exists())
        self.smart_post_redirect(study_id=self.session_study.id)
        self.assertEqual(Participant.objects.count(), 1)
        
        content = self.redirect_get_contents(self.session_study.id)
        new_participant: Participant = Participant.objects.first()
        self.assert_present("Created a new patient", content)
        self.assert_present(new_participant.patient_id, content)


class CreateManyParticipant(ResearcherSessionTest):
    ENDPOINT_NAME = "participant_administration.create_many_patients"
    
    @patch("api.participant_administration.s3_upload")
    @patch("api.participant_administration.create_client_key_pair")
    def test(self, create_client_keypair: MagicMock, s3_upload: MagicMock):
        # this test does not make calls to S3
        self.set_session_study_relation(ResearcherRole.researcher)
        self.assertFalse(Participant.objects.exists())
        
        resp: FileResponse = self.smart_post(
            self.session_study.id, desired_filename="something.csv", number_of_new_patients=10
        )
        output_file = b""
        for i, file_bytes in enumerate(resp.streaming_content, start=1):
            output_file = output_file + file_bytes
        
        self.assertEqual(i, 10)
        self.assertEqual(Participant.objects.count(), 10)
        for patient_id in Participant.objects.values_list("patient_id", flat=True):
            self.assert_present(patient_id, output_file)


#
## other_researcher_apis
#

class TestAPIGetStudies(DataApiTest):
    
    ENDPOINT_NAME = "other_researcher_apis.get_studies"
    
    def test_data_access_credential_upgrade(self):
        # check our assumptions make sense, set algorithm to sha1 and generate old-style credentials
        self.assertEqual(Researcher.DESIRED_ALGORITHM, "sha256")  # testing assumption
        self.assertEqual(Researcher.DESIRED_ITERATIONS, 1000)  # testing assumption
        self.session_researcher.DESIRED_ALGORITHM = "sha1"
        self.session_access_key, self.session_secret_key = self.session_researcher.reset_access_credentials()
        self.session_researcher.DESIRED_ALGORITHM = "sha256"
        # grab the old-style credentials, run the test_no_study test to confirm it works at all.
        original_database_value = self.session_researcher.access_key_secret
        resp = self.smart_post_status_code(200)
        self.assertEqual(Study.objects.count(), 0)
        self.assertEqual(json.loads(resp.content), {})
        # get any new credentials, make sure they're sha256
        self.session_researcher.refresh_from_db()
        self.assertNotEqual(original_database_value, self.session_researcher.access_key_secret)
        self.assertIn("sha1", original_database_value)
        self.assertIn("sha256", self.session_researcher.access_key_secret)
        # and then make sure the same password works again!
        resp = self.smart_post_status_code(200)
        self.assertEqual(Study.objects.count(), 0)
        self.assertEqual(json.loads(resp.content), {})
    
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
    ENDPOINT_NAME = "other_researcher_apis.get_studies"
    
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
        # Weird, but keep it, useful when debugging this test.
        self.session_researcher.access_key_secret = "apples"
        self.assertRaises(ValidationError, self.session_researcher.save)
    
    def test_wrong_secret_key_db(self):
        # Weird, but keep it, useful when debugging this test.
        the_id = self.session_researcher.id  # instantiate the researcher, get their id
        # have to bypass validation
        Researcher.objects.filter(id=the_id).update(access_key_secret="apples")
        resp = self.smart_post()
        # key doesn't match, forbidden
        self.assertEqual(403, resp.status_code)
    
    def test_wrong_secret_key_post(self):
        resp = self.less_smart_post(access_key="apples", secret_key=self.session_secret_key)
        # key doesn't match, forbidden
        self.assertEqual(403, resp.status_code)
    
    def test_wrong_access_key_db(self):
        # Weird, but keep it, useful when debugging this test.
        self.session_researcher.access_key_id = "apples"
        self.session_researcher.save()
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
    ENDPOINT_NAME = "other_researcher_apis.get_users_in_study"
    
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
        self.smart_post_status_code(404, study_id='a'*24)
    
    def test_bad_object_id(self):
        # 0 is an invalid study id
        self.smart_post_status_code(400, study_id='['*24)
        self.smart_post_status_code(400, study_id='a'*5)
    
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
    ENDPOINT_NAME = "other_researcher_apis.get_users_in_study"
    
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
    ENDPOINT_NAME = "other_researcher_apis.download_study_interventions"
    
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
        correct_output = {self.DEFAULT_PARTICIPANT_NAME:
                            {self.DEFAULT_SURVEY_OBJECT_ID:
                                {self.DEFAULT_INTERVENTION_NAME: self.CURRENT_DATE.isoformat()}}}
        self.assertDictEqual(json_unpacked, correct_output)


#
## data_access_api
#

class TestGetData(DataApiTest):
    """ WARNING: there are heisenbugs in debugging the download data api endpoint.

    There is a generator that is conditionally present (`handle_database_query`), it can swallow
    errors. As a generater iterating over it consumes it, so printing it breaks the code.
    
    You Must Patch libs.streaming_zip.ThreadPool
        The database connection breaks throwing errors on queries that should succeed.
        The iterator inside the zip file generator generally fails, and the zip file is empty.

    You Must Patch libs.streaming_zip.s3_retrieve
        Otherwise s3_retrieve will fail due to the patch is tests.common.
    """
    
    def test_s3_patch_present(self):
        from libs import s3
        self.assertIs(s3.S3_BUCKET, Exception)
    
    ENDPOINT_NAME = "data_access_api.get_data"
    
    EMPTY_ZIP = b'PK\x05\x06\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    SIMPLE_FILE_CONTENTS = b"this is the file content you are looking for"
    REGISTRY_HASH = "registry_hash"
    
    # retain and usethis structure in order to force a test addition on a new file type.
    # "particip" is the DEFAULT_PARTICIPANT_NAME
    # 'u1Z3SH7l2xNsw72hN3LnYi96' is the  DEFAULT_SURVEY_OBJECT_ID
    PATIENT_NAME = CommonTestCase.DEFAULT_PARTICIPANT_NAME
    FILE_NAMES = {                                        # ↓ that Z makes it a timzone'd datetime
        "accelerometer": ("something.csv", "2020-10-05 02:00Z",
                         f"{PATIENT_NAME}/accelerometer/2020-10-05 02_00_00+00_00.csv"),
        "ambient_audio": ("something.mp4", "2020-10-05 02:00Z",
                         f"{PATIENT_NAME}/ambient_audio/2020-10-05 02_00_00+00_00.mp4"),
        "app_log": ("app_log.csv", "2020-10-05 02:00Z",
                         f"{PATIENT_NAME}/app_log/2020-10-05 02_00_00+00_00.csv"),
        "bluetooth": ("bluetooth.csv", "2020-10-05 02:00Z",
                         f"{PATIENT_NAME}/bluetooth/2020-10-05 02_00_00+00_00.csv"),
        "calls": ("calls.csv", "2020-10-05 02:00Z",
                         f"{PATIENT_NAME}/calls/2020-10-05 02_00_00+00_00.csv"),
        "devicemotion": ("devicemotion.csv", "2020-10-05 02:00Z",
                         f"{PATIENT_NAME}/devicemotion/2020-10-05 02_00_00+00_00.csv"),
        "gps": ("gps.csv", "2020-10-05 02:00Z",
                         f"{PATIENT_NAME}/gps/2020-10-05 02_00_00+00_00.csv"),
        "gyro": ("gyro.csv", "2020-10-05 02:00Z",
                         f"{PATIENT_NAME}/gyro/2020-10-05 02_00_00+00_00.csv"),
        "identifiers": ("identifiers.csv", "2020-10-05 02:00Z",
                         f"{PATIENT_NAME}/identifiers/2020-10-05 02_00_00+00_00.csv"),
        "image_survey": ("image_survey/survey_obj_id/something/something2.csv", "2020-10-05 02:00Z",
                         # patient_id/data_type/survey_id/survey_instance/name.csv
                         f"{PATIENT_NAME}/image_survey/survey_obj_id/something/something2.csv"),
        "ios_log": ("ios_log.csv", "2020-10-05 02:00Z",
                         f"{PATIENT_NAME}/ios_log/2020-10-05 02_00_00+00_00.csv"),
        "magnetometer": ("magnetometer.csv", "2020-10-05 02:00Z",
                         f"{PATIENT_NAME}/magnetometer/2020-10-05 02_00_00+00_00.csv"),
        "power_state": ("power_state.csv", "2020-10-05 02:00Z",
                         f"{PATIENT_NAME}/power_state/2020-10-05 02_00_00+00_00.csv"),
        "proximity": ("proximity.csv", "2020-10-05 02:00Z",
                         f"{PATIENT_NAME}/proximity/2020-10-05 02_00_00+00_00.csv"),
        "reachability": ("reachability.csv", "2020-10-05 02:00Z",
                         f"{PATIENT_NAME}/reachability/2020-10-05 02_00_00+00_00.csv"),
        "survey_answers": ("survey_obj_id/something2/something3.csv", "2020-10-05 02:00Z",
                          # expecting: patient_id/data_type/survey_id/time.csv
                         f"{PATIENT_NAME}/survey_answers/something2/2020-10-05 02_00_00+00_00.csv"),
        "survey_timings": ("something1/something2/something3/something4/something5.csv", "2020-10-05 02:00Z",
                          # expecting: patient_id/data_type/survey_id/time.csv
                          f"{PATIENT_NAME}/survey_timings/u1Z3SH7l2xNsw72hN3LnYi96/2020-10-05 02_00_00+00_00.csv"),
        "texts": ("texts.csv", "2020-10-05 02:00Z",
                         f"{PATIENT_NAME}/texts/2020-10-05 02_00_00+00_00.csv"),
        "audio_recordings": ("audio_recordings.wav", "2020-10-05 02:00Z",
                         f"{PATIENT_NAME}/audio_recordings/2020-10-05 02_00_00+00_00.wav"),
        "wifi": ("wifi.csv", "2020-10-05 02:00Z",
                         f"{PATIENT_NAME}/wifi/2020-10-05 02_00_00+00_00.csv"),
        }
    
    # setting the threadpool needs to apply to each test, following this pattern because its easy.
    @patch("libs.streaming_zip.ThreadPool")
    def test_basics(self, threadpool: MagicMock):
        threadpool.return_value = DummyThreadPool()
        self._test_basics(as_site_admin=False)
    
    @patch("libs.streaming_zip.ThreadPool")
    def test_basics_as_site_admin(self, threadpool: MagicMock):
        threadpool.return_value = DummyThreadPool()
        self._test_basics(as_site_admin=True)
    
    @patch("libs.streaming_zip.ThreadPool")
    def test_downloads_and_file_naming(self, threadpool: MagicMock):
        threadpool.return_value = DummyThreadPool()
        self._test_downloads_and_file_naming()
    
    @patch("libs.streaming_zip.ThreadPool")
    def test_registry_doesnt_download(self, threadpool: MagicMock):
        threadpool.return_value = DummyThreadPool()
        self._test_registry_doesnt_download()
    
    @patch("libs.streaming_zip.ThreadPool")
    def test_time_bin(self, threadpool: MagicMock):
        threadpool.return_value = DummyThreadPool()
        self._test_time_bin()
    
    @patch("libs.streaming_zip.ThreadPool")
    def test_user_query(self, threadpool: MagicMock):
        threadpool.return_value = DummyThreadPool()
        self._test_user_query()
    
    @patch("libs.streaming_zip.ThreadPool")
    def test_data_streams(self, threadpool: MagicMock):
        threadpool.return_value = DummyThreadPool()
        self._test_data_streams()
    
    # but don't patch ThreadPool for this one
    def test_downloads_and_file_naming_heisenbug(self):
        # As far as I can tell the ThreadPool seems to screw up the connection to the test
        # database, and queries on the non-main thread either find no data or connect to the wrong
        # database (presumably your normal database?).
        # Please retain this behavior and consult me (Eli, Biblicabeebli) during review.  This means a
        # change has occurred to the multithreading, and is probably related to an obscure but known
        # memory leak in the data access api download enpoint that is relevant on large downloads. """
        try:
            self._test_downloads_and_file_naming()
        except AssertionError as e:
            # this will happen on the first file it tests, accelerometer.
            literal_string_of_error_message = f"b'{self.PATIENT_NAME}/accelerometer/2020-10-05 " \
                "02_00_00+00_00.csv' not found in b'PK\\x05\\x06\\x00\\x00\\x00\\x00\\x00" \
                "\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00'"
            
            if str(e) != literal_string_of_error_message:
                raise Exception(
                    f"\n'{literal_string_of_error_message}'\nwas not equal to\n'{str(e)}'\n"
                    "\n  You have changed something that is possibly related to "
                    "threading via a ThreadPool or DummyThreadPool"
                )
    
    def _test_basics(self, as_site_admin: bool):
        if as_site_admin:
            self.session_researcher.update(site_admin=True)
        else:
            self.set_session_study_relation(ResearcherRole.researcher)
        resp: FileResponse = self.smart_post(study_pk=self.session_study.id, web_form="anything")
        self.assertEqual(resp.status_code, 200)
        for i, file_bytes in enumerate(resp.streaming_content, start=1):
            pass
        self.assertEqual(i, 1)
        # this is an empty zip file as output by the api.  PK\x05\x06 is zip-speak for an empty
        # container.  Behavior can vary on how zip decompressors handle an empty zip, some fail.
        self.assertEqual(file_bytes, self.EMPTY_ZIP)
        
        # test without web_form, which will create the registry file (which is empty)
        resp2: FileResponse = self.smart_post(study_pk=self.session_study.id)
        self.assertEqual(resp2.status_code, 200)
        file_content = b""
        for i2, file_bytes2 in enumerate(resp2.streaming_content, start=1):
            file_content = file_content + file_bytes2
        self.assertEqual(i2, 2)
        self.assert_present(b"registry{}", file_content)
    
    @patch("libs.streaming_zip.s3_retrieve")
    def _test_downloads_and_file_naming(self, s3_retrieve: MagicMock):
        # basics
        s3_retrieve.return_value = self.SIMPLE_FILE_CONTENTS
        self.set_session_study_relation(ResearcherRole.researcher)
        
        # need to test all data types
        for data_type in ALL_DATA_STREAMS:
            path, time_bin, output_name = self.FILE_NAMES[data_type]
            file_contents = self.generate_chunkregistry_and_download(data_type, path, time_bin)
            # this is an 'in' test because the file name is part of the zip file, as cleartext
            self.assertIn(output_name.encode(), file_contents)
            self.assertIn(s3_retrieve.return_value, file_contents)
    
    @patch("libs.streaming_zip.s3_retrieve")
    def _test_data_streams(self, s3_retrieve: MagicMock):
        # basics
        s3_retrieve.return_value = self.SIMPLE_FILE_CONTENTS
        self.set_session_study_relation(ResearcherRole.researcher)
        file_path = "some_file_path.csv"
        basic_args = ("accelerometer", file_path, "2020-10-05 02:00Z")
        
        # assert normal args actually work
        file_contents = self.generate_chunkregistry_and_download(*basic_args)
        self.assertNotEqual(file_contents, self.EMPTY_ZIP)
        
        # test matching data type downloads
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args, query_data_streams='["accelerometer"]'
        )
        self.assertNotEqual(file_contents, self.EMPTY_ZIP)
        # same with only the string (no brackets, client.post handles serialization)
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args, query_data_streams="accelerometer"
        )
        self.assertNotEqual(file_contents, self.EMPTY_ZIP)
        
        # test invalid data stream
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args, query_data_streams='"[accelerometer,gyro]', status_code=404
        )
        
        # test valid, non-matching data type does not download
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args, query_data_streams='["gyro"]'
        )
        self.assertEqual(file_contents, self.EMPTY_ZIP)
    
    @patch("libs.streaming_zip.s3_retrieve")
    def _test_registry_doesnt_download(self, s3_retrieve: MagicMock):
        # basics
        s3_retrieve.return_value = self.SIMPLE_FILE_CONTENTS
        self.set_session_study_relation(ResearcherRole.researcher)
        file_path = "some_file_path.csv"
        basic_args = ("accelerometer", file_path, "2020-10-05 02:00Z")
        
        # assert normal args actually work
        file_contents = self.generate_chunkregistry_and_download(*basic_args)
        self.assertNotEqual(file_contents, self.EMPTY_ZIP)
        
        # test that file is not downloaded when a valid json registry is present
        # (the test for the empty zip is much, easiest, even if this combination of parameters
        # is technically not kosher.)
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args, registry=json.dumps({file_path: self.REGISTRY_HASH}), force_web_form=True
        )
        self.assertEqual(file_contents, self.EMPTY_ZIP)
        
        # test that a non-matching hash does not block download.
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args, registry=json.dumps({file_path: "bad hash value"})
        )
        self.assertNotEqual(file_contents, self.EMPTY_ZIP)
        
        # test bad json objects
        self.generate_chunkregistry_and_download(
            *basic_args, registry=json.dumps([self.REGISTRY_HASH]), status_code=400
        )
        self.generate_chunkregistry_and_download(
            *basic_args, registry=json.dumps([file_path]), status_code=400
        )
        # empty string is probably worth testing
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args, registry="", status_code=400
        )
    
    @patch("libs.streaming_zip.s3_retrieve")
    def _test_time_bin(self, s3_retrieve: MagicMock):
        # basics
        s3_retrieve.return_value = self.SIMPLE_FILE_CONTENTS
        self.set_session_study_relation(ResearcherRole.researcher)
        basic_args = ("accelerometer", "some_file_path.csv", "2020-10-05 02:00Z")
        
        # generic request should succeed
        file_contents = self.generate_chunkregistry_and_download(*basic_args)
        self.assertNotEqual(file_contents, self.EMPTY_ZIP)
        self.assertIn(self.SIMPLE_FILE_CONTENTS, file_contents)
        
        # the api time parameter format is "%Y-%m-%dT%H:%M:%S"
        # from a time before time_bin of chunkregistry
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args, query_time_bin_start="2020-10-05T01:00:00",
        )
        self.assertNotEqual(file_contents, self.EMPTY_ZIP)
        self.assertIn(self.SIMPLE_FILE_CONTENTS, file_contents)
        
        # inner check should be equal to or after the given date
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args, query_time_bin_start="2020-10-05T02:00:00",
        )
        self.assertNotEqual(file_contents, self.EMPTY_ZIP)
        self.assertIn(self.SIMPLE_FILE_CONTENTS, file_contents)
        
        # inner check should be equal to or before the given date
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args, query_time_bin_end="2020-10-05T02:00:00",
        )
        self.assertNotEqual(file_contents, self.EMPTY_ZIP)
        self.assertIn(self.SIMPLE_FILE_CONTENTS, file_contents)
        
        # this should fail, start date is late
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args, query_time_bin_start="2020-10-05T03:00:00",
        )
        self.assertEqual(file_contents, self.EMPTY_ZIP)
        
        # this should succeed, end date is after start date
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args, query_time_bin_end="2020-10-05T03:00:00",
        )
        self.assertNotEqual(file_contents, self.EMPTY_ZIP)
        self.assertIn(self.SIMPLE_FILE_CONTENTS, file_contents)
        
        # should succeed, within time range
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args,
            query_time_bin_start="2020-10-05T02:00:00",
            query_time_bin_end="2020-10-05T03:00:00",
        )
        self.assertNotEqual(file_contents, self.EMPTY_ZIP)
        self.assertIn(self.SIMPLE_FILE_CONTENTS, file_contents)
        
        # test with bad time bins, returns no data, user error, no special case handling
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args,
            query_time_bin_start="2020-10-05T03:00:00",
            query_time_bin_end="2020-10-05T02:00:00",
        )
        self.assertEqual(file_contents, self.EMPTY_ZIP)
        
        # test inclusive
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args,
            query_time_bin_start="2020-10-05T02:00:00",
            query_time_bin_end="2020-10-05T02:00:00",
        )
        self.assertNotEqual(file_contents, self.EMPTY_ZIP)
        self.assertIn(self.SIMPLE_FILE_CONTENTS, file_contents)
        
        # test bad time format
        self.generate_chunkregistry_and_download(
            *basic_args, query_time_bin_start="2020-10-05 01:00:00", status_code=400
        )
    
    @patch("libs.streaming_zip.s3_retrieve")
    def _test_user_query(self, s3_retrieve: MagicMock):
        # basics
        s3_retrieve.return_value = self.SIMPLE_FILE_CONTENTS
        self.set_session_study_relation(ResearcherRole.researcher)
        basic_args = ("accelerometer", "some_file_path.csv", "2020-10-05 02:00Z")
        
        # generic request should succeed
        file_contents = self.generate_chunkregistry_and_download(*basic_args)
        self.assertNotEqual(file_contents, self.EMPTY_ZIP)
        self.assertIn(self.SIMPLE_FILE_CONTENTS, file_contents)
        
        # Test bad username
        output_status_code = self.generate_chunkregistry_and_download(
            *basic_args, query_patient_ids='["jeff"]', status_code=404
        )
        self.assertEqual(output_status_code, 404)  # redundant, whatever
        
        # test working participant filter
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args, query_patient_ids=[self.default_participant.patient_id],
        )
        self.assertNotEqual(file_contents, self.EMPTY_ZIP)
        self.assertIn(self.SIMPLE_FILE_CONTENTS, file_contents)
        # same but just the string
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args, query_patient_ids=self.default_participant.patient_id,
        )
        self.assertNotEqual(file_contents, self.EMPTY_ZIP)
        self.assertIn(self.SIMPLE_FILE_CONTENTS, file_contents)
        
        # test empty patients doesn't do anything
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args, query_patient_ids='[]',
        )
        self.assertNotEqual(file_contents, self.EMPTY_ZIP)
        self.assertIn(self.SIMPLE_FILE_CONTENTS, file_contents)
        
        # test no matching data. create user, query for that user
        self.generate_participant(self.session_study, "jeff")
        file_contents = self.generate_chunkregistry_and_download(
            *basic_args, query_patient_ids='["jeff"]',
        )
        self.assertEqual(file_contents, self.EMPTY_ZIP)
    
    def generate_chunkregistry_and_download(
        self,
        data_type: str,
        file_path: str,
        time_bin: str,
        status_code: int = 200,
        registry: bool = None,
        query_time_bin_start: str = None,
        query_time_bin_end: str = None,
        query_patient_ids: str = None,
        query_data_streams: str = None,
        force_web_form: bool = False,
    ):
        post_kwargs = {"study_pk": self.session_study.id}
        generate_kwargs = {"time_bin": time_bin, "path": file_path}
        tracking = {"researcher": self.session_researcher, "query_params": {}}
        
        if data_type == SURVEY_TIMINGS:
            generate_kwargs["survey"] = self.default_survey
        
        if registry is not None:
            post_kwargs["registry"] = registry
            generate_kwargs["hash_value"] = self.REGISTRY_HASH  # strings must match
            tracking["registry_dict_size"] = True
        else:
            post_kwargs["web_form"] = ""
        
        if force_web_form:
            post_kwargs["web_form"] = ""
        
        if query_data_streams is not None:
            post_kwargs["data_streams"] = query_data_streams
            tracking["query_params"]["data_streams"] = query_data_streams
        
        if query_patient_ids is not None:
            post_kwargs["user_ids"] = query_patient_ids
            tracking["user_ids"] = query_patient_ids
        
        if query_time_bin_start:
            post_kwargs['time_start'] = query_time_bin_start
            tracking['time_start'] = query_time_bin_start
        if query_time_bin_end:
            post_kwargs['time_end'] = query_time_bin_end
            tracking['time_end'] = query_time_bin_end
        
        # clear records, create chunkregistry and post
        DataAccessRecord.objects.all().delete()  # we automate tihs testing, easiest to clear it
        self.generate_chunkregistry(
            self.session_study, self.default_participant, data_type, **generate_kwargs
        )
        resp: FileResponse = self.smart_post(**post_kwargs)
        
        # some basics for testing that DataAccessRecords are created
        assert DataAccessRecord.objects.count() == 1, (post_kwargs, resp.status_code, DataAccessRecord.objects.count())
        record = DataAccessRecord.objects.order_by("-created_on").first()
        self.assertEqual(record.researcher.id, self.session_researcher.id)
        
        # Test for a status code, default 200
        self.assertEqual(resp.status_code, status_code)
        if resp.status_code != 200:
            # no iteration, clear db
            ChunkRegistry.objects.all().delete()
            return resp.status_code
        
        # directly comparing these dictionaries is quite non-trivial, not really worth testing tbh?
        # post_kwargs.pop("web_form")
        # self.assertEqual(json.loads(record.query_params), post_kwargs)
        
        # then iterate over the streaming output and concatenate it.
        bytes_list = []
        for i, file_bytes in enumerate(resp.streaming_content, start=1):
            bytes_list.append(file_bytes)
            # print(data_type, i, file_bytes)
        
        # database cleanup has to be after the iteration over the file contents
        ChunkRegistry.objects.all().delete()
        return b"".join(bytes_list)


#
## push_notifications_api
#
class TestPushNotificationSetFCMToken(ParticipantSessionTest):
    ENDPOINT_NAME = "push_notifications_api.set_fcm_token"
    
    def test_no_params_bug(self):
        # this was a 1 at start of writing tests due to a bad default value in the declaration.
        self.assertEqual(ParticipantFCMHistory.objects.count(), 0)
        
        self.session_participant.update(push_notification_unreachable_count=1)
        # FIXME: no parameters results in a 204, it should fail with a 400.
        self.smart_post_status_code(204)
        # FIXME: THIS ASSERT IS A BUG! it should be 1!
        self.assertEqual(ParticipantFCMHistory.objects.count(), 0)
    
    def test_unregister_existing(self):
        # create a new "valid" registration token (not unregistered)
        token_1 = ParticipantFCMHistory(
            participant=self.session_participant, token="some_value", unregistered=None
        )
        token_1.save()
        self.smart_post(fcm_token="some_new_value")
        token_1.refresh_from_db()
        self.assertIsNotNone(token_1.unregistered)
        token_2 = ParticipantFCMHistory.objects.last()
        self.assertNotEqual(token_1.id, token_2.id)
        self.assertIsNone(token_2.unregistered)
    
    def test_reregister_existing_valid(self):
        self.assertIsNone(self.default_participant.last_set_fcm_token)
        # create a new "valid" registration token (not unregistered)
        token = ParticipantFCMHistory(
            participant=self.session_participant, token="some_value", unregistered=None
        )
        token.save()
        # test only the one token exists
        first_time = token.last_updated
        self.smart_post(fcm_token="some_value")
        # test remains unregistered, but token still updated
        token.refresh_from_db()
        second_time = token.last_updated
        self.assertIsNone(token.unregistered)
        self.assertNotEqual(first_time, second_time)
        # test last_set_fcm_token was set
        self.session_participant.refresh_from_db()
        self.assertIsInstance(self.default_participant.last_set_fcm_token, datetime)
    
    def test_reregister_existing_unregister(self):
        # create a new "valid" registration token (not unregistered)
        token = ParticipantFCMHistory(
            participant=self.session_participant, token="some_value", unregistered=timezone.now()
        )
        token.save()
        # test only the one token exists
        first_time = token.last_updated
        self.smart_post(fcm_token="some_value")
        # test is to longer unregistered, and was updated
        token.refresh_from_db()
        second_time = token.last_updated
        self.assertIsNone(token.unregistered)
        self.assertNotEqual(first_time, second_time)

#
## push_notifications_api
#
class TestResendPushNotifications(ResearcherSessionTest):
    ENDPOINT_NAME = "push_notifications_api.resend_push_notification"
    
    def do_post(self):
        # the post operation that all the tests use...
        return self.smart_post_status_code(
            302,
            self.session_study.pk,
            self.default_participant.patient_id,
            survey_id=self.default_survey.pk
        )
    
    def test_bad_fcm_token(self):  # check_firebase_instance: MagicMock):
        self.set_session_study_relation(ResearcherRole.researcher)
        token = self.generate_fcm_token(self.default_participant)
        token.update(unregistered=timezone.now())
        self.assertEqual(self.default_participant.fcm_tokens.count(), 1)
        self.do_post()
        self.assertEqual(self.default_participant.fcm_tokens.count(), 1)
        archived_event = self.default_participant.archived_events.latest("created_on")
        self.assertEqual(archived_event.status, DEVICE_HAS_NO_REGISTERED_TOKEN)
        self.validate_scheduled_event(archived_event)
    
    def test_no_fcm_token(self):  # check_firebase_instance: MagicMock):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.assertEqual(self.default_participant.fcm_tokens.count(), 0)
        self.do_post()
        self.assertEqual(self.default_participant.fcm_tokens.count(), 0)
        archived_event = self.default_participant.archived_events.latest("created_on")
        self.assertEqual(archived_event.status, DEVICE_HAS_NO_REGISTERED_TOKEN)
        self.validate_scheduled_event(archived_event)
    
    def test_no_firebase_creds(self):  # check_firebase_instance: MagicMock):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.generate_fcm_token(self.default_participant)
        self.do_post()
        archived_event = self.default_participant.archived_events.latest("created_on")
        self.assertEqual(archived_event.status, PUSH_NOTIFICATIONS_NOT_CONFIGURED)
        self.validate_scheduled_event(archived_event)
    
    def test_400(self):
        # missing survey_id
        self.set_session_study_relation(ResearcherRole.researcher)
        self.generate_fcm_token(self.default_participant)
        self.smart_post_status_code(400, self.session_study.pk, self.default_participant.patient_id)
    
    @patch("api.push_notifications_api.send_push_notification")
    @patch("api.push_notifications_api.check_firebase_instance")
    def test_mocked_firebase_valueerror_error_1(
        self, check_firebase_instance: MagicMock, send_push_notification: MagicMock
    ):
        # manually invoke some other ValueError to validate that dumb logic.
        check_firebase_instance.return_value = True
        send_push_notification.side_effect = ValueError('something exploded')
        self.set_session_study_relation(ResearcherRole.researcher)
        self.generate_fcm_token(self.default_participant)
        self.do_post()
        archived_event = self.default_participant.archived_events.latest("created_on")
        self.assertIn(MESSAGE_SEND_FAILED_UNKNOWN, archived_event.status)
        self.validate_scheduled_event(archived_event)
    
    @patch("api.push_notifications_api.check_firebase_instance")
    def test_mocked_firebase_valueerror_2(self, check_firebase_instance: MagicMock):
        # by failing to patch messages.send we trigger a valueerror because firebase creds aren't
        #  present is not configured, it is passed to the weird firebase clause
        check_firebase_instance.return_value = True
        self.set_session_study_relation(ResearcherRole.researcher)
        self.generate_fcm_token(self.default_participant)
        self.do_post()
        archived_event = self.default_participant.archived_events.latest("created_on")
        self.assertIn("The default Firebase app does not exist.", archived_event.status)
        self.assertIn("Firebase Error,", archived_event.status)
        self.validate_scheduled_event(archived_event)
    
    @patch("api.push_notifications_api.send_push_notification")
    @patch("api.push_notifications_api.check_firebase_instance")
    def test_mocked_firebase_unregistered_error(
        self, check_firebase_instance: MagicMock, send_push_notification: MagicMock
    ):
        # manually invoke some other ValueError to validate that dumb logic.
        check_firebase_instance.return_value = True
        from firebase_admin.messaging import UnregisteredError
        err_msg = 'UnregisteredError occurred'
        send_push_notification.side_effect = UnregisteredError(err_msg)
        self.set_session_study_relation(ResearcherRole.researcher)
        self.generate_fcm_token(self.default_participant)
        self.do_post()
        archived_event = self.default_participant.archived_events.latest("created_on")
        self.assertIn("Firebase Error,", archived_event.status)
        self.assertIn(err_msg, archived_event.status)
        self.validate_scheduled_event(archived_event)
    
    @patch("api.push_notifications_api.send_push_notification")
    @patch("api.push_notifications_api.check_firebase_instance")
    def test_mocked_generic_error(
        self, check_firebase_instance: MagicMock, send_push_notification: MagicMock
    ):
        # mock generic error on sending the notification
        check_firebase_instance.return_value = True
        send_push_notification.side_effect = Exception('something exploded')
        self.set_session_study_relation(ResearcherRole.researcher)
        self.generate_fcm_token(self.default_participant)
        self.do_post()
        archived_event = self.default_participant.archived_events.latest("created_on")
        self.assertEqual(MESSAGE_SEND_FAILED_UNKNOWN, archived_event.status)
        self.validate_scheduled_event(archived_event)
    
    @patch("api.push_notifications_api.check_firebase_instance")
    @patch("api.push_notifications_api.send_push_notification")
    def test_mocked_success(self, check_firebase_instance: MagicMock, messaging: MagicMock):
        check_firebase_instance.return_value = True
        self.set_session_study_relation(ResearcherRole.researcher)
        self.generate_fcm_token(self.default_participant)
        self.do_post()
        archived_event = self.default_participant.archived_events.latest("created_on")
        self.assertIn(MESSAGE_SEND_SUCCESS, archived_event.status)
        self.validate_scheduled_event(archived_event)
    
    @patch("api.push_notifications_api.check_firebase_instance")
    @patch("api.push_notifications_api.send_push_notification")
    def test_mocked_success_ios(self, check_firebase_instance: MagicMock, messaging: MagicMock):
        check_firebase_instance.return_value = True
        self.default_participant.update(os_type=IOS_API)  # the default os type is android
        self.set_session_study_relation(ResearcherRole.researcher)
        self.generate_fcm_token(self.default_participant)
        self.do_post()
        archived_event = self.default_participant.archived_events.latest("created_on")
        self.assertIn(MESSAGE_SEND_SUCCESS, archived_event.status)
        self.validate_scheduled_event(archived_event)
    
    def validate_scheduled_event(self, archived_event: ArchivedEvent):
        # the scheduled event needs to have some specific qualities
        self.assertEqual(ScheduledEvent.objects.count(), 1)
        one_time_schedule = ScheduledEvent.objects.first()
        self.assertEqual(one_time_schedule.survey_id, self.default_survey.id)
        self.assertEqual(one_time_schedule.checkin_time, None)
        self.assertEqual(one_time_schedule.deleted, True)  # important, don't resend
        self.assertEqual(one_time_schedule.most_recent_event.id, archived_event.id)

#
## forest_pages
#

# FIXME: make a real test...
class TestForestAnalysisProgress(ResearcherSessionTest):
    ENDPOINT_NAME = "forest_pages.forest_tasks_progress"
    
    def test(self):
        # hey it loads...
        self.set_session_study_relation(ResearcherRole.researcher)
        for _ in range(10):
            self.generate_participant(self.session_study)
        # print(Participant.objects.count())
        self.smart_get(self.session_study.id)


# class TestForestCreateTasks(ResearcherSessionTest):
#     ENDPOINT_NAME = "forest_pages.create_tasks"
#     def test(self):
#         self.smart_get()


# class TestForestTaskLog(ResearcherSessionTest):
#     ENDPOINT_NAME = "forest_pages.task_log"
#     def test(self):
#         self.smart_get()


# class TestForestDownloadTaskLog(ResearcherSessionTest):
#     ENDPOINT_NAME = "forest_pages.download_task_log"
#     def test(self):
#         self.smart_get()


# class TestForestCancelTask(ResearcherSessionTest):
#     ENDPOINT_NAME = "forest_pages.cancel_task"
#     def test(self):
#         self.smart_get()


# class TestForestDownloadTaskData(ResearcherSessionTest):
#     ENDPOINT_NAME = "forest_pages.download_task_data"
#     def test(self):
#         self.smart_get()


# class TestForestDownloadOutput(ResearcherSessionTest):
#     ENDPOINT_NAME = "forest_pages.download_task_data"
#     def test(self):
#         self.smart_get()
