from os.path import join as path_join

from constants import DjangoDropdown
from constants.common_constants import BEIWE_PROJECT_ROOT


# Celery Constants
DATA_PROCESSING_CELERY_SERVICE = "services.celery_data_processing"
DATA_PROCESSING_CELERY_QUEUE = "data_processing"
PUSH_NOTIFICATION_SEND_SERVICE = "services.push_notification_send"
PUSH_NOTIFICATION_SEND_QUEUE = "push_notifications"
FOREST_SERVICE = "services.celery_forest"
FOREST_QUEUE = "forest_queue"
SCRIPTS_SERVICE = "services.scripts_runner"
SCRIPTS_QUEUE = "scripts_queue"

CELERY_CONFIG_LOCATION = path_join(BEIWE_PROJECT_ROOT, "manager_ip")

# Push notification constants
ANDROID_FIREBASE_CREDENTIALS = "android_firebase_credentials"
IOS_FIREBASE_CREDENTIALS = "ios_firebase_credentials"
BACKEND_FIREBASE_CREDENTIALS = "backend_firebase_credentials"
# firebase gets the default app name unless otherwise specified, so it is necessary to have
# another name for testing that will never be used to send notifications
FIREBASE_APP_TEST_NAME = 'FIREBASE_APP_TEST_NAME'


# Todo: make the pattern of using this object generic throughout all task processing, not just forest.
class ForestTaskStatus(DjangoDropdown):
    queued = 'queued'
    running = 'running'
    success = 'success'
    error = 'error'
    cancelled = 'cancelled'
