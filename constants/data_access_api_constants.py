# these are the fields required from a values query for use in the ZipGenerator class.
# ZipGenerator is used in the data access api, and in the download task data endpoint for forest tasks.
CHUNK_FIELDS = (
    "pk", "participant_id", "data_type", "chunk_path", "time_bin", "chunk_hash",
    "participant__patient_id", "study_id", "survey_id", "survey__object_id"
)

PARTICIPANT_STATUS_QUERY_FIELDS = (
    "id",
    "created_on",
    "patient_id",
    "registered",
    "os_type",
    "last_upload",
    "last_get_latest_surveys",
    "last_set_password",
    "last_set_fcm_token",
    "last_get_latest_device_settings",
    "last_register_user",
    "permanently_retired",
    "last_heartbeat_checkin",
)

EXTRA_TABLE_FIELDS = {
    "first_register_user": "First Registration Date",
    "last_register_user": "Last Registration",
    "last_upload": "Last Upload",
    "last_get_latest_surveys": "Last Survey Download",
    "last_set_password": "Last Set Password",
    "last_set_fcm_token": "Last Push Token Update",
    "last_get_latest_device_settings": "Last Device Settings Update",
    "last_os_version": "Last OS Version",
    "last_version_code": "App Version Code",
    "last_version_name": "App Version Name",
    "last_heartbeat_checkin": "Last Heartbeat",
}

INCONCEIVABLY_HUGE_NUMBER = 2**64

BASE_TABLE_FIELDS = ["Created On", "Patient ID", "Status", "OS Type"]

MISSING_JSON_CSV_MESSAGE = b"Invalid required data_format parameter, only 'csv' and 'json' supported"