# add the root of the project into the path to allow cd-ing into this folder and running the script.
# from sys import path
# path.insert(0, abspath(__file__).rsplit('/', 2)[0])
from pprint import pprint
from config import load_django

from collections import Counter
from datetime import datetime, timedelta

from config.constants import API_TIME_FORMAT, CHUNKABLE_FILES, REVERSE_UPLOAD_FILE_TYPE_MAPPING
from database.data_access_models import ChunkRegistry
from libs.s3 import s3_list_files

print("This script can take quite a while to run, it depends on the size of the ChunkRegistry database table.")
print("It is strongly recommended that you disable data processing before executing this script.")
print("(ssh and run processing-stop, run processing-start when the script has finished.)")
print("")
print("Finding duplicate file chunks. This needs to be done in a memory-safe, so it could take several minutes.")
print("When this first operation finishes you will start seeing additional output.")
counted = Counter(ChunkRegistry.objects.values_list("chunk_path", flat=True).iterator()).most_common()

duplicate_chunks = []
duplicate_media = []
for chunk_path, count in counted:
    if count == 1:
        break

    if chunk_path.endswith(".csv"):
        duplicate_chunks.append(chunk_path)
    else:
        duplicate_media.append(chunk_path)

del counted

# print("\nmedia file breakdown")
# pprint(dict(Counter([d.rsplit(".",1)[1] for d in duplicate_media])))

duplicate_non_chunkables = []
file_paths_to_reprocess = []
for path in duplicate_chunks:

    # deconstruct relevant information from chunk path, clean it
    path_components = path.split("/")
    if len(path_components) == 5:
        _, study_obj_id, username, data_stream, timestamp = path.split("/")
    elif len(path_components) == 4:
        study_obj_id, username, data_stream, timestamp = path.split("/")
    else:
        raise Exception("invalid_path: %s" % path)

    # not all files are chunkable, they will require different logic.
    if data_stream not in CHUNKABLE_FILES:
        duplicate_non_chunkables.append(path_components)
        continue

    # data stream names are truncated
    full_data_stream = REVERSE_UPLOAD_FILE_TYPE_MAPPING[data_stream]

    # get the initial timestamp
    dt_start = datetime.strptime(timestamp.strip(".csv"), API_TIME_FORMAT)
    dt_prev = dt_start - timedelta(hours=1)
    dt_end = dt_start + timedelta(hours=1)

    file_prefix = "/".join((study_obj_id, username, full_data_stream,)) + "/"
    print(file_prefix)

    # unfortunately we just have to brute force the file paths and convert their timestamps,
    # they are at least sorted alphanumerically.
    prior_hour_last_file = None
    for pf in s3_list_files(file_prefix, as_generator=False):

        file_timestamp = float(pf.rsplit("/")[-1][:-4]) / 1000  # convert timestamp
        file_dt = datetime.fromtimestamp(file_timestamp)

        # we need to get the last file from teh prior hour as it my have data from the relevant hour.
        if dt_prev <= file_dt < dt_start:
            prior_hour_last_file = pf

        # and then every file within the relevant hour
        if dt_start <= file_dt <= dt_end:
            print(pf)
            file_paths_to_reprocess.append(pf)

    if prior_hour_last_file:
        print(prior_hour_last_file)
        file_paths_to_reprocess.append(prior_hour_last_file)

input("waiting....2")

