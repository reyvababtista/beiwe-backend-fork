from collections import Counter
from pprint import pprint

from config.constants import ALL_DATA_STREAMS
from database.data_access_models import FileToProcess
from database.profiling_models import UploadTracking
from database.system_models import FileProcessLock
from libs.dev_utils import p
from libs.file_processing.file_processing_core import process_file_chunks
from libs.file_processing.utility_functions_simple import s3_file_path_to_data_type

FileToProcess.objects.all().delete()
FileProcessLock.unlock()
UploadTracking.re_add_files_to_process(100)

print("File Types in play")

counter = Counter(
        s3_file_path_to_data_type(ftp)
        for ftp in FileToProcess.objects.values_list("s3_file_path", flat=True)
    )

pprint(counter)

for stream_type in ALL_DATA_STREAMS:
    if stream_type not in counter:
        print(f"still missing '{stream_type}'")

print("\n\nOKAY STARTING\n\n")

p()
process_file_chunks()
p()

print("\n\nOKAY DONE")
