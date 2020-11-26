# This file contains the class and necessary functions for the general data container
# class that we use.
import sys
import traceback

from config.constants import CHUNKABLE_FILES
from database.data_access_models import FileToProcess
from libs.file_processing.utility_functions_simple import s3_file_path_to_data_type
from libs.s3 import s3_retrieve


class SomeException(Exception): pass
class SomeException2(Exception): pass

class FileForProcessing():
    def __init__(self, file_to_process: FileToProcess):
        self.file_to_process = file_to_process
        self.data_type = s3_file_path_to_data_type(file_to_process.s3_file_path)
        self.chunkable = self.data_type in CHUNKABLE_FILES
        # self.file_contents = self.get_file_contents()

        self._file_contents = None

        # state tracking
        self.exception = None
        self.traceback = None

        # magically populate at instantiation for now due to networking paradigm.
        self.file_contents


    # todo: is this as a lazy property workable?
    @property
    def file_contents(self):
        # do not catch hasattr("_file_contents"), we intentionally remove the attribute
        # to force a different error type here if accessed after it is deleted
        if self._file_contents is None:
            self._file_contents = self.get_file_contents()
        return self._file_contents

    def clear_file_content(self):
        del self._file_contents

    def set_file_contents(self, new_contents: bytes):
        if not hasattr(self, "_file_contents"):
            raise SomeException2("this happened at the wrong time")
        if not isinstance(new_contents, bytes):
            raise TypeError("only bytes allowed")
        self._file_contents = new_contents

    def get_file_contents(self) -> bytes or None:
        """ Handles network errors and updates state accordingly """
        # Try to retrieve the file contents. If any errors are raised, store them to be raised by the
        # parent function
        try:
            return s3_retrieve(
                self.file_to_process.s3_file_path,
                self.file_to_process.study.object_id,
                raw_path=True
            )
        except Exception as e:
            traceback.print_exc()
            self.traceback = sys.exc_info()
            self.exception = e
            raise SomeException(e)

    def raise_data_processing_error(self):
        """
        If we encountered any errors in retrieving the files for processing, they have been
        lumped together into data['exception']. Raise them here to the error handler and
        move to the next file.
        """
        print("\n" + self.file_to_process.s3_file_path)
        print(self.traceback)
        ################################################################
        # YOU ARE SEEING THIS EXCEPTION WITHOUT A STACK TRACE
        # BECAUSE IT OCCURRED INSIDE POOL.MAP ON ANOTHER THREAD
        ################################################################
        raise self.exception
