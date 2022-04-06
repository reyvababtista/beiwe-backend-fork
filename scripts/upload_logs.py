from subprocess import check_output

from django.utils import timezone

from libs.s3 import s3_upload_plaintext
from libs.sentry import make_error_sentry, SentryTypes


# this script runs periodically. The default system logrotate periodicity for the amazon
# ubuntu 18.04 image is weekly, as long as this script is run more frequently than that 
# all log data in the auth log will be uploaded.


with make_error_sentry(SentryTypes.data_processing):
    with open("/var/log/auth.log") as f:
        auth_log = f.read()

    now = timezone.now().isoformat()
    
    # should be something like ip-172-31-67-107
    hostname = check_output("hostname").strip().decode()
    
    # file name should sort by hostname then date
    s3_upload_plaintext(f"LOGS/auth_log/{hostname}-{now}.log", auth_log)
