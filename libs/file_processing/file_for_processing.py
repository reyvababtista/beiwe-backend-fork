# This file contains the class and necessary functions for the general data container
# class that we use.
from database.data_access_models import FileToProcess


class FileForProcessing():
    def __init__(self, file_to_process: FileToProcess):
        self.exception = None
        self.chunkable = self.determine_chunkable()
        self.data_type = self.determine_data_type()

        self.file_to_process = file_to_process
        # self.s3_file_path = self.file_to_process.s3_file_path  # nope, not necessary

        self.file_contents = self.get_file_contents()

    def determine_chunkable(self) -> bool:
        pass

    def determine_data_type(self) -> str:
        pass

    def get_file_contents(self) -> str:
        pass
