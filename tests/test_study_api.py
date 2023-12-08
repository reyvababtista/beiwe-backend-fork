import json
from datetime import date, datetime, timedelta

from django.utils import timezone

from constants.common_constants import API_DATE_FORMAT
from constants.user_constants import ResearcherRole
from database.schedule_models import Intervention
from database.study_models import StudyField
from tests.common import ResearcherSessionTest


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
            "draw":
                1,
            "start":
                0,
            "length":
                10,
            # sort, sort order, search term.  order key is index into this list, larger values
            # target first interventions then custom fields:
            # ['created_on', 'patient_id', 'registered', 'os_type']
            self.COLUMN_ORDER_KEY:
                0,
            self.ORDER_DIRECTION_KEY:
                "asc",
            self.SEARCH_PARAMETER:
                "",
        }
    
    def CONSTRUCT_RESPONSE(self, status: str):
        return {
            "draw":
                1,
            "recordsTotal":
                1,
            "recordsFiltered":
                1,
            "data":
                [
                    [
                        self.SOME_TIMESTAMP.strftime(API_DATE_FORMAT),
                        self.default_participant.patient_id, status, "ANDROID"
                    ]
                ]
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
            resp = self.smart_post_status_code(
                200, self.session_study.id, **self.DEFAULT_PARAMETERS
            )
            self.assertDictEqual(
                json.loads(resp.content), self.CONSTRUCT_RESPONSE("Active (just now)")
            )
        
        t = timezone.now() - timedelta(minutes=6)
        for status_field_name in self.THE_STATUS_FIELD_NAMES:
            self.default_participant.update_only(**{**fields_as_nones, **{status_field_name: t}})
            resp = self.smart_post_status_code(
                200, self.session_study.id, **self.DEFAULT_PARAMETERS
            )
            self.assertDictEqual(
                json.loads(resp.content), self.CONSTRUCT_RESPONSE("Active (last hour)")
            )
        
        t = timezone.now() - timedelta(hours=2)
        for status_field_name in self.THE_STATUS_FIELD_NAMES:
            self.default_participant.update_only(**{**fields_as_nones, **{status_field_name: t}})
            resp = self.smart_post_status_code(
                200, self.session_study.id, **self.DEFAULT_PARAMETERS
            )
            self.assertDictEqual(
                json.loads(resp.content), self.CONSTRUCT_RESPONSE("Active (past day)")
            )
        
        t = timezone.now() - timedelta(days=2)
        for status_field_name in self.THE_STATUS_FIELD_NAMES:
            self.default_participant.update_only(**{**fields_as_nones, **{status_field_name: t}})
            resp = self.smart_post_status_code(
                200, self.session_study.id, **self.DEFAULT_PARAMETERS
            )
            self.assertDictEqual(
                json.loads(resp.content), self.CONSTRUCT_RESPONSE("Active (past week)")
            )
    
    def test_with_intervention(self):
        self.default_participant.update_only(created_on=self.SOME_TIMESTAMP)
        # need to populate some database state, this database stat is expected to be populated when
        # a participant is created and/or when an intervention is created.
        self.default_intervention
        self.default_populated_intervention_date
        resp = self.smart_post_status_code(200, self.session_study.id, **self.DEFAULT_PARAMETERS)
        content = json.loads(resp.content.decode())
        correct_content = self.CONSTRUCT_RESPONSE("Inactive")
        correct_content["data"][0].append(
            self.CURRENT_DATE.strftime(API_DATE_FORMAT)
        )  # the value populated in the intervention date
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
        self.generate_intervention_date(
            p2, self.default_intervention, None
        )  # correct db population
        # construct the correct response data (yuck)
        correct_content = self.CONSTRUCT_RESPONSE("Inactive")
        correct_content["recordsTotal"] = 2
        correct_content["recordsFiltered"] = 2
        correct_content["data"][0].append(self.CURRENT_DATE.strftime(API_DATE_FORMAT))
        correct_content["data"][0].append(self.DEFAULT_PARTICIPANT_FIELD_VALUE)
        # created on, patient id, registered, os_type, intervention date, custom field
        # (registered is based on presence of os_type)
        correct_content["data"].append(
            [p2.created_on.strftime(API_DATE_FORMAT), p2.patient_id, "Inactive", "ANDROID", "", ""]
        )
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
        intervention = self.generate_intervention(
            self.session_study, "obscure_name_of_intervention"
        )
        self.smart_post_redirect(self.session_study.id, intervention=intervention.id)
        self.assertFalse(Intervention.objects.filter(id=intervention.id).exists())


class TestEditIntervention(ResearcherSessionTest):
    ENDPOINT_NAME = "study_api.edit_intervention"
    REDIRECT_ENDPOINT_NAME = "study_api.interventions_page"
    
    def test(self):
        self.set_session_study_relation(ResearcherRole.study_admin)
        intervention = self.generate_intervention(
            self.session_study, "obscure_name_of_intervention"
        )
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
