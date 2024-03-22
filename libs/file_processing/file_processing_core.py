import time
from collections import defaultdict
from datetime import timedelta
from multiprocessing.pool import ThreadPool
from typing import DefaultDict, Dict, Generator, List, Set, Tuple

from cronutils.error_handler import ErrorHandler, null_error_handler
from django.core.exceptions import ValidationError
from django.utils import timezone

from config.settings import CONCURRENT_NETWORK_OPS, FILE_PROCESS_PAGE_SIZE
from constants import common_constants
from constants.data_stream_constants import (ACCELEROMETER, ANDROID_LOG_FILE, CALL_LOG, DEVICEMOTION, GYRO, IDENTIFIERS,
    SURVEY_DATA_FILES, SURVEY_TIMINGS, WIFI)
from constants.user_constants import ANDROID_API
from database.data_access_models import ChunkRegistry, FileToProcess
from database.user_models_participant import Participant
from libs.file_processing.batched_network_operations import batch_upload
from libs.file_processing.csv_merger import CsvMerger
from libs.file_processing.data_fixes import (fix_app_log_file, fix_call_log_csv, fix_identifier_csv,
    fix_survey_timings, fix_wifi_csv)
from libs.file_processing.data_qty_stats import calculate_data_quantity_stats
from libs.file_processing.exceptions import BadTimecodeError
from libs.file_processing.file_for_processing import FileForProcessing
from libs.file_processing.utility_functions_csvs import csv_to_list
from libs.file_processing.utility_functions_simple import (binify_from_timecode,
    clean_java_timecode, resolve_survey_id_from_file_name)
from libs.sentry import SentryTypes, make_error_sentry


def easy_run(participant: Participant):
    """ Just a handy way to just run data processing in the terminal, use with caution, does not
    test for celery activity. """
    print(f"processing files for {participant.patient_id}")
    # number_bad_files = 0
    # while True:
    #     previous_number_bad_files = number_bad_files
    #     starting_length = participant.files_to_process.exclude(deleted=True).count()
    #     print("===")
    #     print(f"{timezone.now()} processing {participant.patient_id}, {starting_length} files remaining")
    #     number_bad_files += do_process_user_file_chunks(
    #         page_size=FILE_PROCESS_PAGE_SIZE,
    #         error_handler=null_error_handler,
    #         position=number_bad_files,
    #         participant=participant,
    #     )
        
    #     print("previous_number_bad_files:", previous_number_bad_files)
    #     print("number_bad_files:", number_bad_files)
    #     print("===")
    #     # If no files were processed, quit processing
    #     if participant.files_to_process.exclude(deleted=True).count() == starting_length:
    #         if previous_number_bad_files == number_bad_files:
    #             # 2 Cases:
    #             #   1) every file broke, blow up. (would cause infinite loop otherwise).
    #             #   2) no new files.
    #             break
    #         else:
    #             continue
    processor = FileProcessingTracker(participant)
    processor.process_user_file_chunks()
    

"""########################## Hourly Update Tasks ###########################"""

# This is useful for testing and profiling behavior. Replaces the imported threadpool with this
# dummy class and poof! Single-threaded so the "threaded" network operations have real stack traces!
# class ThreadPool():
#     def map(self, *args, **kwargs):
#         # cut off any threadpool kwargs, which is conveniently easy because map does not use kwargs!
#         return map(*args)
#     def terminate(self): pass
#     def close(self): pass
#     def __init__(self, *args,**kwargs): pass

class FileProcessingTracker():
    def __init__(
        self, participant: Participant, page_size: int = FILE_PROCESS_PAGE_SIZE,
    ) -> None:
        self.error_handler: ErrorHandler = make_error_sentry(
            sentry_type=SentryTypes.data_processing, tags={'patient_id': participant.patient_id}
        )
        self.participant = participant
        self.study_id = participant.study.object_id
        self.patient_id = participant.patient_id
        
        # we operate on a page of files at a time, this is the size of the page.
        self.page_size = page_size
        
        # A list of valid ids to process. To avoid a situation where the participant uploads files
        # while we are processing them we grab the database ids of the files to process and always
        # pass that in.  In the very unlikely situation that the database reuses ids (never seen on
        # any database ever), this will cause the infinite loop.
        self.pks_to_process: List[int] = list(participant.files_to_process.values_list("pk"))
        
        # we need to keep track of the bad files so we can skip them in the next iteration.
        # this is a viable strategy because some bugs can be resolved by just waiting for the next
        # processing run for the participant. The ovehead of tracking these compared to removing
        # pks from pks_to_process is minimal and it helps with debugging.
        self.bad_pks = []
        
        # It is possible for devices to record data from unreasonable times, like the unix epoch
        # start. This huristic is a safety measure to clear out bad data.
        common_constants.LATEST_POSSIBLE_DATA_TIMESTAMP = \
            int(time.mktime((timezone.now() + timedelta(days=90)).timetuple()))
        
        # a defaultdict of a tuple of 2 lists - this stores the data that is being processed.
        self.all_binified_data: Dict[int, Tuple[List[bytes], List[bytes]]] = defaultdict(lambda: ([], []))
        
        # a dict to store the survey id from the file name, this is a very old design decision and
        # it is bad.
        self.survey_id_dict = {}
        
        # we don't actually use this...
        self.buggy_files = set()
        
        # old shit
        # self.position = 0
    
    def get_paginated_files_to_process(self) -> Generator[List[FileToProcess], None, None]:
        pks = list(
            self.participant.files_to_process
                .filter(pk__in=self.pks_to_process)
                .exclude(deleted=True, pk__in=self.bad_pks)
                .order_by("s3_file_path", "created_on")
        )
        print("Number Files To Process:", len(pks))
        
        ret = []
        for pk in pks:
            ret.append(pk)
            if len(ret) == self.page_size:
                yield ret  # yield 100 files at a time
                ret = []
        yield ret
    
    #
    ## Outer Loop
    #
    
    def process_user_file_chunks(self):
        for page_of_fhps in self.get_paginated_files_to_process():
            print(f"will process {len(page_of_fhps)} files.")
            self.do_process_user_file_chunks(page_of_fhps)
    
    def do_process_user_file_chunks(self, files_to_process: List[FileToProcess]):
        """ Run through the files to process, pull their data, sort data into time bins. Run the
        file through the appropriate logic path based on file type. """
        
        # we use a ThreadPool to downloading multiple files simultaneously.
        pool = ThreadPool(CONCURRENT_NETWORK_OPS)
        
        # This pool pulls in data for each FileForProcessing on a background thread and instantiates it.
        # Instantiating a FileForProcessing object queries S3 for the File's data. (network request)
        files_for_processing: List[FileForProcessing] = pool.map(
            FileForProcessing, files_to_process, chunksize=1
        )
        
        for file_for_processing in files_for_processing:
            with self.error_handler:
                self.process_one_file(file_for_processing)
        
        pool.close()
        pool.terminate()
        
        # there are several failure modes and success modes, information for what to do with different
        # files percolates back to here.  Delete various database objects accordingly.
        ftps_to_remove, more_bad_files, earliest_time_bin, latest_time_bin = self.upload_binified_data()
        self.buggy_files.update(more_bad_files)
        print(f"Successully processed {len(ftps_to_remove)} files, there have been a total of {len(self.buggy_files)} failed files.")
        
        # Update the data quantity stats (if it actually processed any files)
        if len(files_to_process) > 0:
            calculate_data_quantity_stats(self.participant, earliest_time_bin, latest_time_bin)
        
        # Actually delete the processed FTPs from the database now that we are done.
        FileToProcess.objects.filter(pk__in=ftps_to_remove).delete()
        
    def process_one_file(self, file_for_processing: FileForProcessing):
        """ This function is the inner loop of the chunking process. """
        
        if file_for_processing.exception:
            file_for_processing.raise_data_processing_error()
        
        # there are two cases: chunkable data that can be stuck into "time bins" for each hour, and
        # files that do not need to be "binified" and pretty much just go into the ChunkRegistry unmodified.
        if file_for_processing.chunkable:
            self.process_chunkable_file(file_for_processing)
        else:
            self.process_unchunkable_file(file_for_processing)
    
    def upload_binified_data(self) -> Tuple[Set[int], List[int], int, int]:
        """ Takes in binified csv data and handles uploading/downloading+updating
            older data to/from S3 for each chunk.
            Returns a set of concatenations that have succeeded and can be removed.
            Returns the number of failed FTPS so that we don't retry them.
            Returns the earliest and latest time bins handled
            Raises any errors on the passed in ErrorHandler."""
        # failed_ftps = set([])
        # ftps_to_retire = set([])
        # upload_these = []
        
        # # Track the earliest and latest time bins, to return them at the end of the function
        # earliest_time_bin = None
        # latest_time_bin = None
        uploads = CsvMerger(
            self.all_binified_data, self.error_handler, self.survey_id_dict, self.participant
        )
        
        pool = ThreadPool(CONCURRENT_NETWORK_OPS)
        errors = pool.map(batch_upload, uploads.upload_these, chunksize=1)
        for err_ret in errors:
            if err_ret['exception']:
                print(err_ret['traceback'])
                raise err_ret['exception']
        
        pool.close()
        pool.terminate()
        # The things in ftps to retire that are not in failed ftps.
        # len(failed_ftps) will become the number of files to skip in the next iteration.
        return uploads.get_retirees()
    
    #
    ## Chunkable File Processing
    #
    
    def process_chunkable_file(self, file_for_processing: FileForProcessing):
        newly_binified_data, survey_id_hash = self.process_csv_data(file_for_processing)
    
        # survey answers store the survey id in the file name (truly ancient design decision).
        if file_for_processing.data_type in SURVEY_DATA_FILES:
            self.survey_id_dict[survey_id_hash] = resolve_survey_id_from_file_name(
                file_for_processing.file_to_process.s3_file_path
            )
    
        if newly_binified_data:
            self.append_binified_csvs(newly_binified_data, file_for_processing.file_to_process)
        else:
            # delete empty files from FilesToProcess
            self.ftps_to_remove.add(file_for_processing.file_to_process.id)
    
    def append_binified_csvs(
            self,
            new_binified_rows: DefaultDict[tuple, list],
            file_for_processing:  FileToProcess
        ):
        """ Appends new binified rows to existing binified row data structure, in-place. """
        for data_bin, rows in new_binified_rows.items():
            self.all_binified_data[data_bin][0].extend(rows)  # Add data rows
            self.all_binified_data[data_bin][1].append(file_for_processing.pk)  # Add ftp
        return
    
    # TODO: stick on FileForProcessing??
    def process_csv_data(self, file_for_processing: FileForProcessing) -> Tuple[DefaultDict[tuple, list], Tuple[str, str, str, bytes]]:
        """ Constructs a binified dict of a given list of a csv rows, catches csv files with known
            problems and runs the correct logic. Returns None If the csv has no data in it. """
        
        header, csv_rows_list = self.apply_fixes_and_extract_data(file_for_processing)
        
        # Memory saving measure: this data is now stored in its entirety in csv_rows_list
        file_for_processing.clear_file_content()
        
        if file_for_processing.data_type in (IDENTIFIERS, SURVEY_TIMINGS):
            header = self.apply_fixes_2(header, csv_rows_list, file_for_processing)
        
        # sometimes there is whitespace in the header? clean it.
        header = b",".join(tuple(column_name.strip() for column_name in header.split(b",")))
        
        # shove csv rows into their respective time bins
        if csv_rows_list:
            return (
                # return item 1: the data as a defaultdict
                self.binify_csv_rows(csv_rows_list, file_for_processing.data_type, header),
                # return item 2: the tuple that we use as a key for the defaultdict
                (self.study_id, self.patient_id, file_for_processing.data_type, header)
            )
        else:
            return None, None
    
    def apply_fixes_and_extract_data(self, file_for_processing: FileForProcessing) -> Tuple[bytes, List[List[bytes]]]:
        ## FIXES.
        
        # Android
        if file_for_processing.file_to_process.os_type == ANDROID_API:
            
            # the log file is weird, it is almost not a csv, it is more of a time enumerated list of
            # events. we need to fix it to be a csv.
            if file_for_processing.data_type == ANDROID_LOG_FILE:
                file_for_processing.file_contents = fix_app_log_file(
                    file_for_processing.file_contents, file_for_processing.file_to_process.s3_file_path
                )
            
            header, csv_rows_list = csv_to_list(file_for_processing.file_contents)
            
            # two android fixes require the data immediately, so we convert the generator to a list.
            if file_for_processing.data_type == CALL_LOG:
                csv_rows_list = list(csv_rows_list)
                header = fix_call_log_csv(header, csv_rows_list)
            elif file_for_processing.data_type == WIFI:
                csv_rows_list = list(csv_rows_list)
                header = fix_wifi_csv(
                    header, csv_rows_list, file_for_processing.file_to_process.s3_file_path
                )
        
        else:
            # Do fixes for iOS
            header, csv_rows_list = csv_to_list(file_for_processing.file_contents)
        
        # accelerometer, gyro, and devicemotion data an be massive, so we don't want it all in
        # memory at once, for the others this is an optimization?
        # # fixme: is this even true?
        # if file_for_processing.data_type not in (ACCELEROMETER, GYRO, DEVICEMOTION):
        #     csv_rows_list = list(csv_rows_list)
        
        return header, csv_rows_list
    
    def apply_fixes_2(self, header: bytes, csv_rows_list: List[List[bytes]], file_for_processing: FileForProcessing) -> bytes:
        # these fixes are for Android and iOS
        if file_for_processing.data_type == IDENTIFIERS:
            header = fix_identifier_csv(header, csv_rows_list, file_for_processing.file_to_process.s3_file_path)
        elif file_for_processing.data_type == SURVEY_TIMINGS:
            header = fix_survey_timings(header, csv_rows_list, file_for_processing.file_to_process.s3_file_path)
        else:
            raise Exception(f"bad data stream in fixes 2: {file_for_processing.data_type}")
        return header
    
    def binify_csv_rows(self, rows_list: list, str, data_type: str, header: bytes) -> DefaultDict[tuple, list]:
        """ Assumes a clean csv with element 0 in the rows column as a unix(ish) timestamp.
            Sorts data points into the appropriate bin based on the rounded down hour
            value of the entry's unix(ish) timestamp. (based CHUNK_TIMESLICE_QUANTUM)
            Returns a dict of form {(study_id, patient_id, data_type, time_bin, header):rows_lists}. """
        ret = defaultdict(list)
        for row in rows_list:
            # discovered August 7 2017, looks like there was an empty line at the end
            # of a file? row was a [''].
            if row and row[0]:
                # this is the first thing that will hit corrupted timecode values errors (origin of which is unknown).
                try:
                    timecode = binify_from_timecode(row[0])
                except BadTimecodeError:
                    continue
                ret[
                    (self.study_id, self.patient_id, data_type, timecode, header)
                ].append(row)
        return ret
    
    
    #
    ## Unchunkable File Processing
    #
    
    def process_unchunkable_file(file_for_processing: FileForProcessing, ftps_to_remove: set):
        try:
            # if the timecode is bad, we scrap this file. We just don't care.
            timestamp = clean_java_timecode(
                file_for_processing.file_to_process.s3_file_path.rsplit("/", 1)[-1][:-4]
            )
        except BadTimecodeError:
            ftps_to_remove.add(file_for_processing.file_to_process.id)
            return
        
        # Since we aren't binning the data by hour, just create a ChunkRegistry that
        # points to the already existing S3 file.
        try:
            ChunkRegistry.register_unchunked_data(
                file_for_processing.data_type,
                timestamp,
                file_for_processing.file_to_process.s3_file_path,
                file_for_processing.file_to_process.study.pk,
                file_for_processing.file_to_process.participant.pk,
                file_for_processing.file_contents,
            )
            ftps_to_remove.add(file_for_processing.file_to_process.id)
        except ValidationError as ve:
            if len(ve.messages) != 1:
                # case: the error case (below) is very specific, we only want that singular error.
                raise
            
            # case: an unchunkable file was re-uploaded, causing a duplicate file path collision
            # we detect this specific case and update the registry with the new file size
            # (hopefully it doesn't actually change)
            if 'Chunk registry with this Chunk path already exists.' in ve.messages:
                ChunkRegistry.update_registered_unchunked_data(
                    file_for_processing.data_type,
                    file_for_processing.file_to_process.s3_file_path,
                    file_for_processing.file_contents,
                )
                ftps_to_remove.add(file_for_processing.file_to_process.id)
            else:
                # any other errors, add
                raise
        return











# def do_process_user_file_chunks(
#         page_size: int, error_handler: ErrorHandler, position: int, participant: Participant,
# ):
#     """Run through the files to process, pull their data, sort data into time bins. Run the file through
#     the appropriate logic path based on file type.

#     If a file is empty put its ftp object to the empty_files_list, we can't delete objects in-place
#     while iterating over the db.

#     All files except for the audio recording files are in the form of CSVs, most of those files can
#     be separated by "time bin" (separated into one-hour chunks) and concatenated and sorted
#     trivially. A few files, call log, identifier file, and wifi log, require some triage beforehand.
#     The debug log cannot be correctly sorted by time for all elements, because it was not actually
#     expected to be used by researchers, but is apparently quite useful.

#     Any errors are themselves concatenated using the passed in error handler.

#     In a single call to this function, page_size files will be processed,at the position specified.
#     This is expected to exclude files that have previously errored in file processing. (some
#     conflicts can be most easily resolved by just delaying a file until the next processing period.)
    
#     To fix a problem where the server gets stuck processing a single participant's files for a very
#     long time if they are actively uploading faster than their data can be processed a list of
#     allowed pks can be passed in.
#     """
    
#     # FIXME: this is a gross hack to force some time related safety, which is only ever used deep
#     # inside of data processing.
    # common_constants.LATEST_POSSIBLE_DATA_TIMESTAMP = \
#         int(time.mktime((timezone.now() + timedelta(days=90)).timetuple()))
    
#     # Declare a defaultdict of a tuple of 2 lists
#     all_binified_data = defaultdict(lambda: ([], []))
#     ftps_to_remove = set()
#     # The ThreadPool enables downloading multiple files simultaneously from the network, and continuing
#     # to download files as other files are being processed, making the code as a whole run faster.
#     # In principle we could make a global pool that is free-memory aware.
#     pool = ThreadPool(CONCURRENT_NETWORK_OPS)
#     survey_id_dict = {}
    
#     # A Django query with a slice (e.g. .all()[x:y]) makes a LIMIT query, so it
#     # only gets from the database those FTPs that are in the slice.
#     # print(participant.as_dict())
#     print("Number Files To Process:", participant.files_to_process.exclude(deleted=True).count())
#     print(f"will process {page_size} files.")
#     print("current count processing within this run:", position)
    
#     # TODO: investigate, comment.  ordering by path results in files grouped by type and
#     # chronological order, which is perfect for download efficiency... right? would it break anthing?
#     files_to_process = participant.files_to_process \
#         .exclude(deleted=True)  #.order_by("s3_file_path", "created_on")
    
#     # This pool pulls in data for each FileForProcessing on a background thread and instantiates it.
#     # Instantiating a FileForProcessing object queries S3 for the File's data. (network request))
#     files_for_processing = pool.map(
#         FileForProcessing, files_to_process[position: position + page_size], chunksize=1
#     )
    
#     for file_for_processing in files_for_processing:
#         with error_handler:
#             process_one_file(
#                 file_for_processing, survey_id_dict, all_binified_data, ftps_to_remove
#             )
#     pool.close()
#     pool.terminate()
    
#     # there are several failure modes and success modes, information for what to do with different
#     # files percolates back to here.  Delete various database objects accordingly.
#     more_ftps_to_remove, number_bad_files, earliest_time_bin, latest_time_bin = upload_binified_data(
#         all_binified_data, error_handler, survey_id_dict, participant
#     )
#     ftps_to_remove.update(more_ftps_to_remove)
    
#     # Update the data quantity stats, if it actually processed any files
#     if len(files_to_process) > 0:
#         calculate_data_quantity_stats(participant,
#                                       earliest_time_bin_number=earliest_time_bin,
#                                       latest_time_bin_number=latest_time_bin)
    
#     # Actually delete the processed FTPs from the database
#     FileToProcess.objects.filter(pk__in=ftps_to_remove).delete()
#     return number_bad_files


# def process_one_file(
#         file_for_processing: FileForProcessing, survey_id_dict: dict, all_binified_data: DefaultDict,
#         ftps_to_remove: set
# ):
#     """ This function is the inner loop of the chunking process. """
    
#     if file_for_processing.exception:
#         file_for_processing.raise_data_processing_error()
    
#     # there are two cases: chunkable data that can be stuck into "time bins" for each hour, and
#     # files that do not need to be "binified" and pretty much just go into the ChunkRegistry unmodified.
#     if file_for_processing.chunkable:
#         process_chunkable_file(file_for_processing, survey_id_dict, all_binified_data, ftps_to_remove)
#     else:
#         process_unchunkable_file(file_for_processing, ftps_to_remove)


# def process_chunkable_file(
#     file_for_processing: FileForProcessing, survey_id_dict: dict, all_binified_data: DefaultDict,
#     ftps_to_remove: set
# ):
#     newly_binified_data, survey_id_hash = process_csv_data(file_for_processing)
    
#     # survey answers store the survey id in the file name (truly ancient design decision).
#     if file_for_processing.data_type in SURVEY_DATA_FILES:
#         survey_id_dict[survey_id_hash] = resolve_survey_id_from_file_name(
#             file_for_processing.file_to_process.s3_file_path)
    
#     if newly_binified_data:
#         append_binified_csvs(
#             all_binified_data, newly_binified_data, file_for_processing.file_to_process
#         )
#     else:  # delete empty files from FilesToProcess
#         ftps_to_remove.add(file_for_processing.file_to_process.id)


# def process_unchunkable_file(file_for_processing: FileForProcessing, ftps_to_remove: set):
#     try:
#         # if the timecode is bad, we scrap this file. We just don't care.
#         timestamp = clean_java_timecode(
#             file_for_processing.file_to_process.s3_file_path.rsplit("/", 1)[-1][:-4]
#         )
#     except BadTimecodeError:
#         ftps_to_remove.add(file_for_processing.file_to_process.id)
#         return

#     # Since we aren't binning the data by hour, just create a ChunkRegistry that
#     # points to the already existing S3 file.
#     try:
#         ChunkRegistry.register_unchunked_data(
#             file_for_processing.data_type,
#             timestamp,
#             file_for_processing.file_to_process.s3_file_path,
#             file_for_processing.file_to_process.study.pk,
#             file_for_processing.file_to_process.participant.pk,
#             file_for_processing.file_contents,
#         )
#         ftps_to_remove.add(file_for_processing.file_to_process.id)
#     except ValidationError as ve:
#         if len(ve.messages) != 1:
#             # case: the error case (below) is very specific, we only want that singular error.
#             raise
        
#         # case: an unchunkable file was re-uploaded, causing a duplicate file path collision
#         # we detect this specific case and update the registry with the new file size
#         # (hopefully it doesn't actually change)
#         if 'Chunk registry with this Chunk path already exists.' in ve.messages:
#             ChunkRegistry.update_registered_unchunked_data(
#                 file_for_processing.data_type,
#                 file_for_processing.file_to_process.s3_file_path,
#                 file_for_processing.file_contents,
#             )
#             ftps_to_remove.add(file_for_processing.file_to_process.id)
#         else:
#             # any other errors, add
#             raise


# def upload_binified_data(binified_data, error_handler, survey_id_dict, participant):
#     """ Takes in binified csv data and handles uploading/downloading+updating
#         older data to/from S3 for each chunk.
#         Returns a set of concatenations that have succeeded and can be removed.
#         Returns the number of failed FTPS so that we don't retry them.
#         Returns the earliest and latest time bins handled
#         Raises any errors on the passed in ErrorHandler."""
#     # failed_ftps = set([])
#     # ftps_to_retire = set([])
#     # upload_these = []
    
#     # # Track the earliest and latest time bins, to return them at the end of the function
#     # earliest_time_bin = None
#     # latest_time_bin = None
#     uploads = CsvMerger(binified_data, error_handler, survey_id_dict, participant)
    
#     pool = ThreadPool(CONCURRENT_NETWORK_OPS)
#     errors = pool.map(batch_upload, uploads.upload_these, chunksize=1)
#     for err_ret in errors:
#         if err_ret['exception']:
#             print(err_ret['traceback'])
#             raise err_ret['exception']
    
#     pool.close()
#     pool.terminate()
#     # The things in ftps to retire that are not in failed ftps.
#     # len(failed_ftps) will become the number of files to skip in the next iteration.
#     return uploads.get_retirees()


# """############################## Standard CSVs #############################"""

# def binify_csv_rows(rows_list: list, study_id: str, patient_id: str, data_type: str, header: bytes) -> DefaultDict[tuple, list]:
#     """ Assumes a clean csv with element 0 in the rows column as a unix(ish) timestamp.
#         Sorts data points into the appropriate bin based on the rounded down hour
#         value of the entry's unix(ish) timestamp. (based CHUNK_TIMESLICE_QUANTUM)
#         Returns a dict of form {(study_id, patient_id, data_type, time_bin, header):rows_lists}. """
#     ret = defaultdict(list)
#     for row in rows_list:
#         # discovered August 7 2017, looks like there was an empty line at the end
#         # of a file? row was a [''].
#         if row and row[0]:
#             # this is the first thing that will hit corrupted timecode values errors (origin of which is unknown).
#             try:
#                 timecode = binify_from_timecode(row[0])
#             except BadTimecodeError:
#                 continue
#             ret[(study_id, patient_id, data_type, timecode, header)].append(row)
#     return ret


# def append_binified_csvs(old_binified_rows: DefaultDict[tuple, list],
#                          new_binified_rows: DefaultDict[tuple, list],
#                          file_for_processing:  FileToProcess):
#     """ Appends binified rows to an existing binified row data structure.
#         Should be in-place. """
#     for data_bin, rows in new_binified_rows.items():
#         old_binified_rows[data_bin][0].extend(rows)  # Add data rows
#         old_binified_rows[data_bin][1].append(file_for_processing.pk)  # Add ftp


# # TODO: stick on FileForProcessing
# def process_csv_data(file_for_processing: FileForProcessing):
#     """ Constructs a binified dict of a given list of a csv rows,
#         catches csv files with known problems and runs the correct logic.
#         Returns None If the csv has no data in it. """
    
#     if file_for_processing.file_to_process.os_type == ANDROID_API:
#         # Do fixes for Android
#         if file_for_processing.data_type == ANDROID_LOG_FILE:
#             file_for_processing.file_contents = fix_app_log_file(
#                 file_for_processing.file_contents, file_for_processing.file_to_process.s3_file_path
#             )
        
#         header, csv_rows_list = csv_to_list(file_for_processing.file_contents)
#         if file_for_processing.data_type != ACCELEROMETER:
#             # If the data is not accelerometer data, convert the generator to a list.
#             # For accelerometer data, the data is massive and so we don't want it all
#             # in memory at once.
#             csv_rows_list = list(csv_rows_list)
        
#         if file_for_processing.data_type == CALL_LOG:
#             header = fix_call_log_csv(header, csv_rows_list)
#         if file_for_processing.data_type == WIFI:
#             header = fix_wifi_csv(header, csv_rows_list, file_for_processing.file_to_process.s3_file_path)
#     else:
#         # Do fixes for iOS
#         header, csv_rows_list = csv_to_list(file_for_processing.file_contents)
        
#         if file_for_processing.data_type != ACCELEROMETER:
#             csv_rows_list = list(csv_rows_list)
    
#     # Memory saving measure: this data is now stored in its entirety in csv_rows_list
#     file_for_processing.clear_file_content()
    
#     # Do these fixes for data whether from Android or iOS
#     if file_for_processing.data_type == IDENTIFIERS:
#         header = fix_identifier_csv(header, csv_rows_list, file_for_processing.file_to_process.s3_file_path)
#     if file_for_processing.data_type == SURVEY_TIMINGS:
#         header = fix_survey_timings(header, csv_rows_list, file_for_processing.file_to_process.s3_file_path)
    
#     header = b",".join([column_name.strip() for column_name in header.split(b",")])
#     if csv_rows_list:
#         return (
#             # return item 1: the data as a defaultdict
#             binify_csv_rows(
#                 csv_rows_list,
#                 file_for_processing.file_to_process.study.object_id,
#                 file_for_processing.file_to_process.participant.patient_id,
#                 file_for_processing.data_type,
#                 header
#             ),
#             # return item 2: the tuple that we use as a key for the defaultdict
#             (
#                 file_for_processing.file_to_process.study.object_id,
#                 file_for_processing.file_to_process.participant.patient_id,
#                 file_for_processing.data_type,
#                 header
#             )
#         )
#     else:
#         return None, None
