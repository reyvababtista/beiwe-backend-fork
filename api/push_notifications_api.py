import json
from datetime import datetime

from flask import Blueprint, request

from firebase_admin import messaging
from config import constants
from database.user_models import Participant
from libs.user_authentication import authenticate_user, get_session_participant

push_notifications_api = Blueprint('push_notifications_api', __name__)


################################################################################
########################### NOTIFICATION FUNCTIONS #############################
################################################################################


@push_notifications_api.route('/set_fcm_token', methods=['POST'])
@authenticate_user
def set_fcm_token():
    """
    Sets a participants Firebase CLoud Messaging (FCM) instance token, called whenever a new token
    is generated. Expects a patient_id and and fcm_token in the request body.
    """
    participant = get_session_participant()
    participant.fcm_instance_id = request.values['fcm_token']
    participant.save()
    print("Patient", participant.patient_id, "token: ", request.values['fcm_token'])
    return '', 204


@push_notifications_api.route('/test_notification', methods=['POST'])
@authenticate_user
def send_notification():
    """
    Sends a push notification to the participant, used for testing
    Expects a patient_id in the request body.
    """
    participant = request.get_session_participant()
    message = messaging.Message(
        data={
            'type': 'fake',
            'content': 'hello good sir',
        },
        token=participant.fcm_instance_id,
    )
    response = messaging.send(message)
    print('Successfully sent notification message:', response)
    return '', 204


@push_notifications_api.route('/send_survey_notification', methods=['Post'])
@authenticate_user
def send_survey_notification():
    """
    Sends a push notification to the participant with survey data, used for testing
    Expects a patient_id in the request body
    """
    participant = Participant.objects.get(patient_id=request.values['patient_id'])
    token = participant.fcm_instance_id
    survey_ids = [survey.object_id for survey in participant.study.surveys.filter(deleted=False).order_by("?")[:4]]
    survey_ids.sort()
    sent_time = datetime.now().strftime(constants.API_TIME_FORMAT)
    message = messaging.Message(
        data={
            'type': 'survey',
            'survey_ids': json.dumps(survey_ids),
            'sent_time': sent_time,
        },
        token=token,
    )
    response = messaging.send(message)
    print('Successfully sent survey message:', response)
    return '', 204


################################################################################
################################# DOWNLOAD #####################################
################################################################################


@push_notifications_api.route('/download_survey', methods=['GET', 'POST'])
def get_single_survey():
    """
    Sends a json-formatted survey to the participant's phone
    Expects a patient_id and survey_id in the request body
    """
    participant = Participant.objects.get(patient_id=request.values['patient_id'])
    study = participant.study
    survey = study.surveys.get(object_id=request.values["survey_id"])
    return json.dumps(survey.format_survey_for_study())
