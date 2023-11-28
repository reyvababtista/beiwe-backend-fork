import time
from datetime import date, datetime, timedelta
from posixpath import abspath
from sys import argv as _argv

from dateutil.tz import UTC


BEIWE_PROJECT_ROOT = abspath(__file__.rsplit("/", 2)[0] + "/")  # this does not end in a slash...
PROJECT_PARENT_FOLDER = BEIWE_PROJECT_ROOT.rsplit("/", 2)[0] + "/"

RUNNING_TEST_OR_IN_A_SHELL = any(
    key in _argv for key in ("shell_plus", "--ipython", "ipython", "test", "runserver")
)
RUNNING_TESTS = "test" in _argv

# roughly one month before the initial deploy of the first Beiwe instance.
EARLIEST_POSSIBLE_DATA_DATE = date(2014, 8, 1)
EARLIEST_POSSIBLE_DATA_DATETIME = datetime(year=2014, month=8, day=1, tzinfo=UTC)

# this is the integer output of time.mktime(EARLIEST_POSSIBLE_DATA_DATETIME.timetuple())
EARLIEST_POSSIBLE_DATA_TIMESTAMP = 1406851200

# in order to solve a nasty problem that is stalling all data processing in rare cases due to
# corrupted data, we need a sanity check inside data processing.  This value is updated at runtime,
# just in case 90 days somehow isn't enough.
LATEST_POSSIBLE_DATA_TIMESTAMP = int(time.mktime((datetime.utcnow() + timedelta(days=90)).timetuple()))


# The format that dates should be in throughout the codebase
# 1990-01-31T07:30:04 gets you jan 31 1990 at 7:30:04am
# human string is YYYY-MM-DDThh:mm:ss
API_TIME_FORMAT = "%Y-%m-%dT%H:%M:%S"  # this is the isoformat without timezone
API_TIME_FORMAT_WITH_TZ = "%Y-%m-%dT%H:%M:%S (%Z)"
API_DATE_FORMAT = "%Y-%m-%d"
LEGIBLE_TIME_FORMAT = "%Y-%m-%d %H:%M:%S (%Z)"
DEV_TIME_FORMAT = "%Y-%m-%d %H:%M (%Z)"
DEV_TIME_FORMAT3 = "%Y-%m-%d %H:%M:%S . %f (%Z)"  # leave the extra spaces
DISPLAY_TIME_FORMAT = "%Y-%m-%d %-I:%M%p (%Z)"

## All s3 file paths must be declared here so that we know where they are for participant data purge.
CHUNKS_FOLDER = "CHUNKED_DATA"
PROBLEM_UPLOADS = "PROBLEM_UPLOADS"

# file path for custom ondeploy script
CUSTOM_ONDEPLOY_SCRIPT_EB = "CUSTOM_ONDEPLOY_SCRIPT/EB"
CUSTOM_ONDEPLOY_SCRIPT_PROCESSING = "CUSTOM_ONDEPLOY_SCRIPT/PROCESSING"
