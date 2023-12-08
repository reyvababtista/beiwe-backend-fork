import json
from datetime import datetime
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.http.response import FileResponse
from django.utils import timezone

from constants.message_strings import (DEVICE_HAS_NO_REGISTERED_TOKEN, MESSAGE_SEND_FAILED_UNKNOWN,
    MESSAGE_SEND_SUCCESS, NO_DELETION_PERMISSION, PARTICIPANT_LOCKED,
    PUSH_NOTIFICATIONS_NOT_CONFIGURED)
from constants.user_constants import IOS_API, ResearcherRole
from database.schedule_models import ArchivedEvent, ScheduledEvent
from database.study_models import Study
from database.survey_models import Survey
from database.user_models_participant import (Participant, ParticipantDeletionEvent,
    ParticipantFCMHistory)
from database.user_models_researcher import Researcher
from tests.common import DataApiTest, ParticipantSessionTest, ResearcherSessionTest


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
