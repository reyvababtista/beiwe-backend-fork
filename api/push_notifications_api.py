import json
from datetime import datetime

from flask import Blueprint, request

from firebase_admin import messaging
from config import constants
from database.user_models import Participant
from libs.user_authentication import authenticate_user

push_notifications_api = Blueprint('push_notifications_api', __name__)



################################################################################
########################### NOTIFICATION FUNCTIONS #############################
################################################################################


@push_notifications_api.route('/set_fcm_token', methods=['POST'])
@authenticate_user
def set_fcm_token():
    patient_id = request.values['patient_id']
    participant = Participant.objects.get(patient_id=patient_id)
    participant.fcm_instance_id = request.values['fcm_token']
    participant.save()
    print("Patient", patient_id, "token: ", request.values['fcm_token'])
    return '', 204


@push_notifications_api.route('/send_notification', methods=['POST'])
@authenticate_user
def send_notification():
    participant = Participant.objects.get(patient_id=request.values['patient_id'])
    token = participant.fcm_instance_id
    message = messaging.Message(
        data={
            'type': 'fake',
            'content': 'hello good sir',
        },
        token=token,
    )
    response = messaging.send(message)
    print('Successfully sent notification message:', response)
    return '', 204


@push_notifications_api.route('/send_survey_notification', methods=['Post'])
@authenticate_user
def send_survey_notification():
    participant = Participant.objects.get(patient_id=request.values['patient_id'])
    token = participant.fcm_instance_id
    survey_id = participant.study.surveys.first().object_id
    sent_time = datetime.now().strftime(constants.API_TIME_FORMAT)
    message = messaging.Message(
        data={
            'type': 'survey',
            'survey_id': survey_id,
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
    participant = Participant.objects.get(patient_id=request.values['patient_id'])
    study = participant.study
    survey = study.surveys.get(object_id=request.values["survey_id"])
    return json.dumps(survey.format_survey_for_study())
