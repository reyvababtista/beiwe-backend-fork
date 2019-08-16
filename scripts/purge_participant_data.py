# python 2-3 compatibility section
from __future__ import print_function

try:
    input = raw_input
except NameError:
    pass

import imp as _imp
import json
from datetime import datetime
from sys import argv
from os.path import abspath as _abspath

# modify python path so that this script can be targeted directly but still import everything.
_current_folder_init = _abspath(__file__).rsplit('/', 1)[0]+ "/__init__.py"
_imp.load_source("__init__", _current_folder_init)

# noinspection PyUnresolvedReferences
from config import load_django

from config.constants import CHUNKS_FOLDER, API_TIME_FORMAT
from database.user_models import Participant
from database.data_access_models import ChunkRegistry
from libs.file_processing import unix_time_to_string
from libs.s3 import s3_list_files


UNIX_EPOCH_START = datetime(1970,1,1)

DOCUMENTATION = """
This script takes a single command line argument, a file path pointing at a file containing json.
The JSON must look like this:  
    {
        "username_1": "2019-08-24",
        "username_2": "2019-08-25"
    }
That is a dictionary of usernames mapped to a date in unambiguous "YEAR-MONTH-DAY" format.

You can also supply an argument "-y" to skip the confirmation if you intend to run this in the background.
""".strip()

print()  # just a blank line

def humanize_date(date_string):
    """ returns dates as in this form: 'August 24 2019' """
    return convert_date(date_string).strftime("%B %d %Y")

def convert_date(date_string):
    """ transforms the canonical date strings into dates """
    try:
        return datetime.strptime(date_string, "%Y-%m-%d")
    except ValueError as e:
        print("woops, the date '%s' is not in YEAR-MONTH-DAY format." % date_string)
        exit(1)


def setup():
    # determine whether "-y" was provided on the command line
    try:
        argv.pop(argv.index('-y'))
        skip_confirmation = True
    except ValueError:
        skip_confirmation = False

    # basic sanity check
    if len(argv) != 2:
        print(DOCUMENTATION)
        print("you provided %s argument(s)" % len(argv))
        print()
        exit(1)
    else:
        try:
            with open(argv[1], 'r') as file:
                file_json = json.load(file)
        except ValueError as e:
            print("woops, looks like there is a syntax issue in your JSON, the following error was encountered:")
            print(e)
            print()
            exit(1)


    # sort deletees by date.
    sorted_data = sorted(file_json.items(), key=lambda x: x[1])

    # test thata all the participants exist, exit if they don't
    all_patients_exist = True
    for patient_id, _ in sorted_data:
        if not Participant.objects.filter(patient_id=patient_id).exists():
            all_patients_exist = False
            print("Participant '%s' does not exist." % patient_id)
    if not all_patients_exist:
        exit(1)


    # print out info for confirmation
    for participant_name, date in sorted_data:
        print(participant_name, "--", humanize_date(date))

    # force user to confirm
    if not skip_confirmation:
        print()
        msg = input(
            "I hereby confirm that I want to irreparably delete all data for the above users starting on the day listed. (y/n)\n"
        )
        if not msg.lower() == "y":
            print("Exiting...")
            print()
            exit(0)

    return sorted_data

# delete chunk registries
def delete_chunk_registries(sorted_data):
    print()
    for patient_id, date in sorted_data:
        print("removing ChunkRegistry data for %s..." % patient_id)
        date = convert_date(date)
        participant = Participant.objects.filter(patient_id=patient_id)
        ChunkRegistry.objects.filter(participant=participant, time_bin__gte=date).delete()


def assemble_deletable_files(sorted_data):
    deletable_file_paths = []

    for patient_id, expunge_start_date in sorted_data:
        participant = Participant.objects.get(patient_id=patient_id)

        # technically it is a datetime object
        expunge_start_date = convert_date(expunge_start_date)
        expunge_start_unix_timestamp = int((expunge_start_date - UNIX_EPOCH_START).total_seconds()) * 1000
        print(
            patient_id,
            "timestamp: %s, (%s)" %
            (expunge_start_date, expunge_start_unix_timestamp)
        )

        prefix = str(participant.study.object_id) + "/" + patient_id + "/"
        s3_files = s3_list_files(prefix, as_generator=True)

        chunks_prefix = CHUNKS_FOLDER + "/" + prefix
        s3_chunks_files = s3_list_files(chunks_prefix, as_generator=True)

        deletable_file_paths.extend(assemble_raw_files(s3_files, expunge_start_unix_timestamp))
        deletable_file_paths.extend(assemble_chunked_files(s3_chunks_files, expunge_start_date))

    return deletable_file_paths



def assemble_raw_files(s3_file_paths, expunge_timestamp):
    ret = []
    for file_path in s3_file_paths:
        # there may be some corrupt file paths that has _ instead of /
        extracted_timestamp_str = file_path.replace("_", "/").rsplit("/", 1)[1][:-4]
        extracted_timestamp_int = int(extracted_timestamp_str)

        if len(extracted_timestamp_str) == 10:
            extracted_timestamp_int = extracted_timestamp_int * 1000

        if expunge_timestamp <= extracted_timestamp_int:
            ret.append(file_path)
    return ret


def assemble_chunked_files(s3_chunks_files, expunge_start_date):
    ret = []
    for file_path in s3_chunks_files:
        # there may be some corrupt file paths that has _ instead of /
        extracted_timestamp_str = file_path.replace("_", "/").rsplit("/", 1)[1][:-4]
        extracted_dt = datetime.strptime(extracted_timestamp_str, API_TIME_FORMAT)

        if expunge_start_date < extracted_dt:
            ret.append(file_path)
    return ret

setup_data = setup()
delete_chunk_registries(setup_data)
print(assemble_deletable_files(setup_data))
