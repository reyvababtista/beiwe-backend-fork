import calendar
import json
import plistlib
import time

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.http.response import HttpResponse
from django.utils import timezone

from authentication.participant_authentication import (authenticate_participant,
    authenticate_participant_registration, minimal_validation)
from config.settings import REPORT_DECRYPTION_KEY_ERRORS
from constants.celery_constants import ANDROID_FIREBASE_CREDENTIALS, IOS_FIREBASE_CREDENTIALS
from constants.message_strings import (DECRYPTION_KEY_ADDITIONAL_MESSAGE,
    DECRYPTION_KEY_ERROR_MESSAGE, DEVICE_IDENTIFIERS_HEADER, INVALID_EXTENSION_ERROR, NO_FILE_ERROR,
    S3_FILE_PATH_UNIQUE_CONSTRAINT_ERROR, UNKNOWN_ERROR)
from database.data_access_models import FileToProcess
from database.profiling_models import DecryptionKeyError, UploadTracking
from database.system_models import FileAsText
from libs.encryption import decrypt_device_file, DecryptionKeyInvalidError, HandledError
from libs.http_utils import determine_os_api
from libs.internal_types import ParticipantRequest
from libs.push_notification_helpers import repopulate_all_survey_scheduled_events
from libs.s3 import get_client_public_key_string, s3_upload
from libs.sentry import make_sentry_client, SentryTypes
from middleware.abort_middleware import abort


ALLOWED_EXTENSIONS = {'csv', 'json', 'mp4', "wav", 'txt', 'jpg'}

################################################################################
################################ UPLOADS #######################################
################################################################################

@determine_os_api
@minimal_validation
def upload(request: ParticipantRequest, OS_API=""):
    """ Entry point to upload GPS, Accelerometer, Audio, PowerState, Calls Log, Texts Log,
    Survey Response, and debugging files to s3.

    Behavior:
    The Beiwe app is supposed to delete the uploaded file if it receives an html 200 response.
    The API returns a 200 response when the file has A) been successfully handled, B) the file it
    has been sent is empty, C) the file did not decrypt properly.  We encountered problems in
    production with incorrectly encrypted files (as well as Android generating "rList" files
    under unknown circumstances) and the app then uploads them.  When the device receives a 200
    that is its signal to delete the file.
    When a file is undecryptable (this was tracked to a scenario where the device could not
    create/write an AES encryption key) we send a 200 response to stop that device attempting to
    re-upload the data.
    In the event of a single line being undecryptable (can happen due to io errors on the device)
    we drop only that line (and store the erroring line in an attempt to track it down.

    A 400 error means there is something is wrong with the uploaded file or its parameters,
    administrators will be emailed regarding this upload, the event will be logged to the apache
    log.  The app should not delete the file, it should try to upload it again at some point.

    If a 500 error occurs that means there is something wrong server side, administrators will be
    emailed and the event will be logged. The app should not delete the file, it should try to
    upload it again at some point.

    Request format:
    send an http post request to [domain name]/upload, remember to include security
    parameters (see participant_authentication for documentation). Provide the contents of the file,
    encrypted (see encryption specification) and properly converted to Base64 encoded text,
    as a request parameter entitled "file".
    Provide the file name in a request parameter entitled "file_name". """
    
    # Handle these corner cases first because they requires no database input.
    # Crash logs are from truly ancient versions of the android codebase
    # rList are randomly generated by android
    # PersistedInstallation files come from firebase.
    file_name = request.POST.get("file_name", None)
    if (
            not bool(file_name)
            or file_name.startswith("rList")
            or file_name.startswith("PersistedInstallation")
            or not contains_valid_extension(file_name)
    ):
        return HttpResponse(status=200)
    
    s3_file_location = file_name.replace("_", "/")
    participant = request.session_participant
    
    if participant.unregistered:
        # "Unregistered" participants are blocked from uploading further data.
        # If the participant is unregistered, throw away the data file, but
        # return a 200 "OK" status to the phone so the phone decides it can
        # safely delete the file.
        return HttpResponse(status=200)
    
    # block duplicate FTPs.  Testing the upload history is too complex
    if FileToProcess.test_file_path_exists(s3_file_location, participant.study.object_id):
        return HttpResponse(status=200)
    
    uploaded_file = get_uploaded_file(request)
    try:
        uploaded_file = decrypt_device_file(file_name, uploaded_file, participant)
    except HandledError:
        return HttpResponse(status=200)
    except DecryptionKeyInvalidError:
        # when the decryption key is invalid the file is lost.  Nothing we can do.
        # record the event, send the device a 200 so it can clear out the file.
        if REPORT_DECRYPTION_KEY_ERRORS:
            tags = {
                "participant": participant.patient_id,
                "operating system": "ios" if "ios" in request.path.lower() else "android",
                "DecryptionKeyError id": str(DecryptionKeyError.objects.last().id),
                "file_name": file_name,
                "bug_report": DECRYPTION_KEY_ADDITIONAL_MESSAGE,
            }
            sentry_client = make_sentry_client(SentryTypes.elastic_beanstalk, tags)
            sentry_client.captureMessage(DECRYPTION_KEY_ERROR_MESSAGE)
        return HttpResponse(status=200)
    
    # if uploaded data actually exists, and has a valid extension
    if uploaded_file and file_name and contains_valid_extension(file_name):
        s3_upload(s3_file_location, uploaded_file, participant.study.object_id)
        
        # race condition: multiple _concurrent_ uploads with same file path. Behavior without
        # try-except is correct, but we don't care about reporting it. Just send the device a 500
        # error so it skips the file, the followup attempt receives 200 code and deletes the file.
        try:
            FileToProcess.append_file_for_processing(
                s3_file_location, participant.study.object_id, participant=participant
            )
        except ValidationError as e:
            # Real error is a second validation inside e.error_dict["s3_file_path"].
            # Ew; just test for this string instead...
            if S3_FILE_PATH_UNIQUE_CONSTRAINT_ERROR in str(e):
                # this tells the device to just move on to the next file, try again later.
                return abort(500)
            else:
                raise
        
        UploadTracking.objects.create(
            file_path=s3_file_location,
            file_size=len(uploaded_file),
            timestamp=timezone.now(),
            participant=participant,
        )
        return HttpResponse(status=200)
    
    elif not uploaded_file:
        # if the file turns out to be empty, delete it, we simply do not care.
        return HttpResponse(status=200)
    else:
        return make_upload_error_report(participant.patient_id, file_name)


# FIXME: Device Testing. this function exists to handle some ancient behavior, it definitely has
#  details that can be removed, and an error case that can probably go too.
def get_uploaded_file(request: ParticipantRequest):
    # Slightly different values for iOS vs Android behavior.
    # Android sends the file data as standard form post parameter (request.POST)
    # iOS sends the file as a multipart upload (so ends up in request.FILES)
    if "file" in request.FILES:
        # ios
        uploaded_file = request.FILES['file']
    elif "file" in request.POST:
        # android
        uploaded_file = request.POST['file']
    else:
        # no uploaded file, is a bad request.
        return abort(400)
    
    # file should always be an InMemoryUploadedFile
    if isinstance(uploaded_file, (ContentFile, InMemoryUploadedFile)):
        uploaded_file = uploaded_file.read()
    
    if isinstance(uploaded_file, str):
        uploaded_file = uploaded_file.encode()  # android
    elif isinstance(uploaded_file, bytes):
        pass  # nothing needs to happen (ios)
    else:
        raise TypeError(f"uploaded_file was a {type(uploaded_file)}")
    
    return uploaded_file


def make_upload_error_report(patient_id: str, file_name: str):
    """ Does the work of packaging up a useful error message. """
    error_message = "an upload has failed " + patient_id + ", " + file_name + ", "
    if not file_name:
        error_message += NO_FILE_ERROR
    elif file_name and not contains_valid_extension(file_name):
        error_message += INVALID_EXTENSION_ERROR
        error_message += grab_file_extension(file_name)
    else:
        error_message += UNKNOWN_ERROR
    
    tags = {"upload_error": "upload error", "user_id": patient_id}
    sentry_client = make_sentry_client(SentryTypes.elastic_beanstalk, tags)
    sentry_client.captureMessage(error_message)
    return abort(400)


################################################################################
############################## Registration ####################################
################################################################################

@determine_os_api
@authenticate_participant_registration
def register_user(request: ParticipantRequest, OS_API=""):
    """ Checks that the patient id has been granted, and that there is no device registered with
    that id.  If the patient id has no device registered it registers this device and logs the
    bluetooth mac address.
    Check the documentation in participant_authentication to ensure you have provided the proper credentials.
    Returns the encryption key for this patient/user. """
    
    if (
        'patient_id' not in request.POST
        or 'phone_number' not in request.POST
        or 'device_id' not in request.POST
        or 'new_password' not in request.POST
    ):
        return abort(400)
    
    # CASE: If the id and password combination do not match, the decorator returns a 403 error.
    # the following parameter values are required.
    patient_id = request.POST['patient_id']
    phone_number = request.POST['phone_number']
    device_id = request.POST['device_id']
    
    # These values may not be returned by earlier versions of the beiwe app
    device_os = request.POST.get('device_os', "none")
    os_version = request.POST.get('os_version', "none")
    product = request.POST.get("product", "none")
    brand = request.POST.get("brand", "none")
    hardware_id = request.POST.get("hardware_id", "none")
    manufacturer = request.POST.get("manufacturer", "none")
    model = request.POST.get("model", "none")
    beiwe_version = request.POST.get("beiwe_version", "none")
    
    # This value may not be returned by later versions of the beiwe app.
    mac_address = request.POST.get('bluetooth_id', "none")
    
    participant = request.session_participant
    if participant.device_id and participant.device_id != device_id:
        # CASE: this patient has a registered a device already and it does not match this device.
        #   They need to contact the study and unregister their their other device.  The device
        #   will receive a 405 error and should alert the user accordingly.
        # Provided a user does not completely reset their device (which resets the device's
        # unique identifier) they user CAN reregister an existing device, the unlock key they
        # need to enter to at registration is their old password.
        # KG: 405 is good for IOS and Android, no need to check OS_API
        return abort(405)
    
    if participant.os_type and participant.os_type != OS_API:
        # CASE: this patient has registered, but the user was previously registered with a
        # different device type. To keep the CSV munging code sane and data consistent (don't
        # cross the iOS and Android data streams!) we disallow it.
        return abort(400)
    
    # At this point the device has been checked for validity and will be registered successfully.
    # Any errors after this point will be server errors and return 500 codes. the final return
    # will be the encryption key associated with this user.
    
    # Upload the user's various identifiers.
    unix_time = str(calendar.timegm(time.gmtime()))
    file_name = patient_id + '/identifiers_' + unix_time + ".csv"
    
    # Construct a manual csv of the device attributes
    file_contents = (DEVICE_IDENTIFIERS_HEADER + "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s" %
                     (patient_id, mac_address, phone_number, device_id, device_os,
                      os_version, product, brand, hardware_id, manufacturer, model,
                      beiwe_version)).encode()
    
    s3_upload(file_name, file_contents, participant.study.object_id)
    FileToProcess.append_file_for_processing(file_name, participant.study.object_id, participant=participant)
    
    # set up device.
    participant.device_id = device_id
    participant.os_type = OS_API
    participant.set_password(request.POST['new_password'])  # set password saves the model
    device_settings = participant.study.device_settings.as_unpacked_native_python()
    device_settings.pop('_id', None)
    
    # set up FCM files
    firebase_plist_data = None
    firebase_json_data = None
    if participant.os_type == 'IOS':
        ios_credentials = FileAsText.objects.filter(tag=IOS_FIREBASE_CREDENTIALS).first()
        if ios_credentials:
            firebase_plist_data = plistlib.loads(ios_credentials.text.encode())
    elif participant.os_type == 'ANDROID':
        android_credentials = FileAsText.objects.filter(tag=ANDROID_FIREBASE_CREDENTIALS).first()
        if android_credentials:
            firebase_json_data = json.loads(android_credentials.text)
    
    # ensure the survey schedules are updated for this participant.
    repopulate_all_survey_scheduled_events(participant.study, participant)
    
    return_obj = {
        'client_public_key': get_client_public_key_string(patient_id, participant.study.object_id),
        'device_settings': device_settings,
        'ios_plist': firebase_plist_data,
        'android_firebase_json': firebase_json_data,
        'study_name': participant.study.name,
        'study_id': participant.study.object_id,
    }
    return HttpResponse(json.dumps(return_obj))


################################################################################
############################### USER FUNCTIONS #################################
################################################################################


@determine_os_api
@authenticate_participant
def set_password(request: ParticipantRequest, OS_API=""):
    """ After authenticating a user, sets the new password and returns 200.
    Provide the new password in a parameter named "new_password"."""
    new_password = request.POST.get("new_password", None)
    if new_password is None:
        return abort(400)
    request.session_participant.set_password(new_password)
    return HttpResponse(status=200)


################################################################################
########################## FILE NAME FUNCTIONALITY #############################
################################################################################


def grab_file_extension(file_name):
    """ grabs the chunk of text after the final period. """
    return file_name.rsplit('.', 1)[1]


def contains_valid_extension(file_name):
    """ Checks if string has a recognized file extension, this is not necessarily limited to 4 characters. """
    return '.' in file_name and grab_file_extension(file_name) in ALLOWED_EXTENSIONS


################################################################################
################################# DOWNLOAD #####################################
################################################################################


@determine_os_api
@authenticate_participant
def get_latest_surveys(request: ParticipantRequest, OS_API=""):
    survey_json_list = []
    for survey in request.session_participant.study.surveys.filter(deleted=False):
        # Exclude image surveys for the Android app to avoid crashing it
        if not (OS_API == "ANDROID" and survey.survey_type == "image_survey"):
            survey_json_list.append(survey.format_survey_for_study())
    return HttpResponse(json.dumps(survey_json_list))
