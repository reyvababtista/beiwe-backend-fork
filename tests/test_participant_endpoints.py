from unittest.mock import MagicMock, patch

from django.http.response import FileResponse
from django.utils import timezone

from constants.message_strings import (DEVICE_HAS_NO_REGISTERED_TOKEN, MESSAGE_SEND_FAILED_UNKNOWN,
    MESSAGE_SEND_SUCCESS, NO_DELETION_PERMISSION, PARTICIPANT_LOCKED,
    PUSH_NOTIFICATIONS_NOT_CONFIGURED)
from constants.user_constants import IOS_API, ResearcherRole
from database.schedule_models import ArchivedEvent, ScheduledEvent
from database.user_models_participant import Participant, ParticipantDeletionEvent
from tests.common import ResearcherSessionTest


#
## participant endpoints
#


class TestDeleteParticipant(ResearcherSessionTest):
    ENDPOINT_NAME = "participant_endpoints.delete_participant"
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
            self.redirect_get_contents(
                patient_id=self.default_participant.patient_id, study_id=study2.id
            )
        )
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.is_dead, False)
    
    def test_bad_participant(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.smart_post_redirect(patient_id="invalid", study_id=self.session_study.id)
        self.assert_present(
            "does not exist",
            self.easy_get(
                "study_endpoints.view_study_page", status_code=200, study_id=self.session_study.id
            ).content
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
        from endpoints import participant_endpoints
        from pages import participant_pages
        return (
            patch.object(participant_pages, "DATA_DELETION_ALLOWED_RELATIONS", the_patch),
            patch.object(participant_endpoints, "DATA_DELETION_ALLOWED_RELATIONS", the_patch),
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
    ENDPOINT_NAME = "participant_endpoints.reset_participant_password"
    REDIRECT_ENDPOINT_NAME = "participant_pages.participant_page"
    
    def test_success(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        old_password = self.default_participant.password
        self.smart_post_redirect(
            study_id=self.session_study.id, patient_id=self.default_participant.patient_id
        )
        self.default_participant.refresh_from_db()
        self.assert_present(
            "password has been reset to",
            self.easy_get(
                "study_endpoints.view_study_page", status_code=200, study_id=self.session_study.id
            ).content
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
                "study_endpoints.view_study_page", status_code=200, study_id=self.session_study.id
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
            self.easy_get(
                "study_endpoints.view_study_page", status_code=200, study_id=self.session_study.id
            ).content
        )
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.password, old_password)
    
    def test_deleted_participant(self):
        self.set_session_study_relation(ResearcherRole.researcher)
        self.default_participant.update(deleted=True)
        old_password = self.default_participant.password
        self.smart_post_redirect(
            study_id=self.session_study.id, patient_id=self.default_participant.patient_id
        )
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.password, old_password)
        page = self.redirect_get_contents(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        self.assert_present(
            PARTICIPANT_LOCKED.format(patient_id=self.default_participant.patient_id), page
        )


class TestResetDevice(ResearcherSessionTest):
    ENDPOINT_NAME = "participant_endpoints.clear_device_id"
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
            self.easy_get(
                "study_endpoints.view_study_page", status_code=200, study_id=self.session_study.id
            ).content
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
            self.easy_get(
                "study_endpoints.view_study_page", status_code=200, study_id=self.session_study.id
            ).content
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
            self.easy_get(
                "study_endpoints.view_study_page", status_code=200, study_id=self.session_study.id
            ).content
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
        self.assert_present(
            PARTICIPANT_LOCKED.format(patient_id=self.default_participant.patient_id), page
        )
        self.default_participant.refresh_from_db()
        self.assertEqual(self.default_participant.device_id, "12345")


class TestToggleParticipantEasyEnrollment(ResearcherSessionTest):
    ENDPOINT_NAME = "participant_endpoints.toggle_easy_enrollment"
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
        self.smart_post_redirect(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
        self.default_participant.refresh_from_db()
        self.assertTrue(self.default_participant.easy_enrollment)
        self.smart_post_redirect(
            patient_id=self.default_participant.patient_id, study_id=self.session_study.id
        )
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
        self.assert_present(
            PARTICIPANT_LOCKED.format(patient_id=self.default_participant.patient_id), page
        )


class TestUnregisterParticipant(ResearcherSessionTest):
    ENDPOINT_NAME = "participant_endpoints.retire_participant"
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
            self.easy_get(
                "study_endpoints.view_study_page", status_code=200, study_id=self.session_study.id
            ).content
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
            self.easy_get(
                "study_endpoints.view_study_page", status_code=200, study_id=self.session_study.id
            ).content
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
            self.easy_get(
                "study_endpoints.view_study_page", status_code=200, study_id=self.session_study.id
            ).content,
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
            self.easy_get(
                "study_endpoints.view_study_page", status_code=200, study_id=self.session_study.id
            ).content
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
    ENDPOINT_NAME = "participant_endpoints.create_new_participant"
    REDIRECT_ENDPOINT_NAME = "study_endpoints.view_study_page"
    
    @patch("endpoints.participant_endpoints.s3_upload")
    @patch("endpoints.participant_endpoints.create_client_key_pair")
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
    ENDPOINT_NAME = "participant_endpoints.create_many_patients"
    
    @patch("endpoints.participant_endpoints.s3_upload")
    @patch("endpoints.participant_endpoints.create_client_key_pair")
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


class TestResendPushNotifications(ResearcherSessionTest):
    ENDPOINT_NAME = "participant_endpoints.resend_push_notification"
    
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
    
    @patch("endpoints.participant_endpoints.send_push_notification")
    @patch("endpoints.participant_endpoints.check_firebase_instance")
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
    
    @patch("endpoints.participant_endpoints.check_firebase_instance")
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
    
    @patch("endpoints.participant_endpoints.send_push_notification")
    @patch("endpoints.participant_endpoints.check_firebase_instance")
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
    
    @patch("endpoints.participant_endpoints.send_push_notification")
    @patch("endpoints.participant_endpoints.check_firebase_instance")
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
    
    @patch("endpoints.participant_endpoints.check_firebase_instance")
    @patch("endpoints.participant_endpoints.send_push_notification")
    def test_mocked_success(self, check_firebase_instance: MagicMock, messaging: MagicMock):
        check_firebase_instance.return_value = True
        self.set_session_study_relation(ResearcherRole.researcher)
        self.generate_fcm_token(self.default_participant)
        self.do_post()
        archived_event = self.default_participant.archived_events.latest("created_on")
        self.assertIn(MESSAGE_SEND_SUCCESS, archived_event.status)
        self.validate_scheduled_event(archived_event)
    
    @patch("endpoints.participant_endpoints.check_firebase_instance")
    @patch("endpoints.participant_endpoints.send_push_notification")
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
