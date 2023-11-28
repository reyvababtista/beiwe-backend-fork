from typing import Generator, List, Optional, Tuple

import boto3
import zstd
from botocore.client import BaseClient, Paginator
from cronutils import ErrorHandler
from Cryptodome.PublicKey import RSA

from config.settings import (BEIWE_SERVER_AWS_ACCESS_KEY_ID, BEIWE_SERVER_AWS_SECRET_ACCESS_KEY,
    S3_BUCKET, S3_REGION_NAME)
from constants.compression_constants import ZSTD_EXTENSION
from constants.common_constants import CHUNKS_FOLDER

from database.study_models import Study
from database.user_models_participant import Participant
from libs.aes import decrypt_server, encrypt_for_server
from libs.internal_types import StrOrParticipantOrStudy
from libs.rsa import generate_key_pairing, get_RSA_cipher, prepare_X509_key_for_java


# NOTE: S3_BUCKET is patched during tests to be the Exception class, which is (obviously) invalid.
# The asserts in this file are protections for runninsg s3 commands inside tests.


class NoSuchKeyException(Exception): pass
class S3DeleteException(Exception): pass


conn: BaseClient = boto3.client(
    's3',
    aws_access_key_id=BEIWE_SERVER_AWS_ACCESS_KEY_ID,
    aws_secret_access_key=BEIWE_SERVER_AWS_SECRET_ACCESS_KEY,
    region_name=S3_REGION_NAME,
)


class S3Compressed:
    """ Class that coordinates the logic of downloading, uploading, decrypting, and decompressing. """
    
    def __init__(self, s3_path: str, obj: StrOrParticipantOrStudy, bypass_study_folder: bool):
        # the .zstd compression is final, it is appended to the end of the file name for accounting
        # purposes. External code should pass in an unmodified s3_path and this class handles 
        # transforming it. (currently the transformation is simply to append .zstd)
        self.s3_path: str = s3_path
        
        #! fixme: its not clear if knowing that a file is a duplicate is useful as an object property.
        # self.s3_path_normalized: str = self.normalize_s3_file_path(s3_path)
        
        self.bypass_study_folder = bypass_study_folder
        self.smart_key_obj = obj
        # self.has_decryption_key = False  # set to true when we have a decryption key?
        
        self.raw_data = None
        self.final_data = None
        self.is_downloaded = False
    
    @property
    def is_compressed(self) -> bool:
        """ If the s3 path ends with .zstd that means the file on s3 is compressed. Any upload will
        be in compressed form (that's the purpose of this whole class). """
        return self.s3_path.endswith(ZSTD_EXTENSION)
    
    def download(self) -> None:
        """ Downloads, decrypts, decompresses the file from S3. """
        # only download once, call appropriate download function.
        if not self.is_downloaded:
            if self.is_compressed:
                self._download_as_uncompressed()
            else:
                self._download_as_compressed()
    
    def _download_as_uncompressed(self) -> None:
        """ Only to be called by self.download()! This is a destructive operation!
        Downloads the uncompressed(!) file, compresses it, re-uploads it to S3 in compressed form,
        then deletes the old file from s3. """
        self.raw_data = s3_retrieve(self.path_to_non_zstd_path, self.smart_key_obj, self.bypass_study_folder)
        self.push_data(self.raw_data)  # compresses, sets self.s3_path
        s3_delete(self.path_to_non_zstd_path)   #! FIXME: we removed the s3_delete function in favor of (I think) versioned delete. need to check and update
    
    def _download_as_compressed(self) -> None:
        """ Only to be called by self.download()! Downloads the data, sticks it on self.raw_data.
        We do it this way for 2 reasons: it is useful to be able to control when the network request
        happens, 2) it reduces memory overhead to not decompress it until we need it. """
        self.raw_data = s3_retrieve(self.path_to_zstd_path, self.smart_key_obj, self.bypass_study_folder)
        self.s3_path = self.path_to_zstd_path
    
    def get_data(self) -> bytes:
        """ Returns bytes of the file, may run the download ~loop. """
        # if we have already downloaded the file already, just return it.
        if self.final_data is not None:
            return self.final_data
        
        # download, decompress, return. (decrypt is handled in download.)
        self.download()
        self.decompress_data()
        return self.final_data
    
    def decompress_data(self) -> None:
        """ Runs the data decompression process if it has not already run. Clears self.raw_data. """
        if self.is_compressed:
            self.final_data = zstd.decompress(self.raw_data)
            # don't keep the raw data around once we have decompressed it.
            self.raw_data = None
    
    def push_data(self, data: bytes, clear_raw_data: bool = False) -> None:
        """ compresses the data, uploads it to s3. Sets self.s3_path to zstd path. """
        compressed_data = zstd.compress(
            data,
            1,  # compression level (1 yields better compression on average across our data streams
            0,  # auto-tune the number of threads based on cpu cores (no apparent drawbacks)
        )
        
        # Memory usage optimization: raw_data may be large, if the outer code we doesn't need it
        # anymore we can delete it. Ideally all references to that raw_data bytes object are local
        # (on and only on this object, with no external scope references) and it can be cleared out.
        if clear_raw_data:
            self.raw_data = None
            self.is_downloaded = False
        
        # Do the upload (memory usage will be duplicated, possibly triplicated due to python-to-C
        # transition) due to the encryption step.
        s3_upload(self.path_to_zstd_path, compressed_data, self.smart_key_obj, raw_path=self.bypass_study_folder)
        self.s3_path = self.path_to_zstd_path
    
    @property
    def path_to_zstd_path(self) -> str:
        return self.path_to_non_zstd_path + ZSTD_EXTENSION
    
    @property
    def path_to_non_zstd_path(self) -> str:
        #! FIXME: does this do exactly what I want it to do? strip iterates over the string? its weird
        return self.s3_path.rstrip(ZSTD_EXTENSION)
    
    @staticmethod
    def normalize_s3_file_path(s3_file_path: str) -> str:
        """ Takes an s3 file path and returns the normalized version of it.  Normalization currently
        consists of stripping the .zstd extension and the -duplicate-<random string> suffix."""
        s3_file_path = s3_file_path.rstrip(".zstd")
        if "duplicate" in s3_file_path:
            # duplicate files are named blahblah/datastream/unixtime.csv-duplicate-[rando-string]
            return s3_file_path.split("-duplicate")[0]
        else:
            return s3_file_path


def smart_get_study_encryption_key(obj: StrOrParticipantOrStudy) -> bytes:
    """ Takes a string (of a study object_id), or a participant, or a study, and grabs the
    encryption from the study. """
    # participant is the slowest because study is a foreign key.
    if isinstance(obj, Participant):
        return obj.study.encryption_key.encode()
    elif isinstance(obj, Study):
        return obj.encryption_key.encode()
    elif isinstance(obj, str) and len(obj) == 24:
        return Study.objects.values_list("encryption_key", flat=True).get(object_id=obj).encode()
    else:
        raise TypeError(f"expected Study, Participant, or str, received '{type(obj)}'")


def s3_construct_study_key_path(key_path: str, obj: StrOrParticipantOrStudy) -> str:
    """ obj can be a string (of a study object_id), or a participant, or a study. inserts the study
    object_id at the start of the key path. """
    if isinstance(obj, Participant):
        study_object_id = obj.study.object_id
    elif isinstance(obj, Study):
        study_object_id = obj.object_id
    elif isinstance(obj, str) and len(obj) == 24:
        study_object_id = obj
    else:
        raise TypeError(f"expected Study, Participant, or 24 char str, received '{type(obj)}'")
    return study_object_id + "/" + key_path


def s3_upload(
    key_path: str, data_string: bytes, obj: StrOrParticipantOrStudy, raw_path=False
) -> None:
    """ Uploads a bytes object as a file, encrypted using the encryption key of the study it is
    associated with. Intelligently accepts a string, Participant, or Study object as needed. """
    if not raw_path:
        key_path = s3_construct_study_key_path(key_path, obj)
    data = encrypt_for_server(data_string, smart_get_study_encryption_key(obj))
    assert S3_BUCKET is not Exception, "libs.s3.s3_upload called inside test"
    _do_upload(key_path, data)


def _do_upload(key_path: str, data_string: bytes, number_retries=3):
    """ In ~April 2022 this api call started occasionally failing, so wrapping it in a retry. """
    assert S3_BUCKET is not Exception, "libs.s3._do_upload called inside test"
    try:
        conn.put_object(Body=data_string, Bucket=S3_BUCKET, Key=key_path)
    except Exception as e:
        if "Please try again" not in str(e):
            raise
        _do_upload(key_path, data_string, number_retries=number_retries - 1)


def s3_upload_plaintext(upload_path: str, data_string: bytes) -> None:
    """ Extremely simple, uploads a file (bytes object) to s3 without any encryption. """
    conn.put_object(Body=data_string, Bucket=S3_BUCKET, Key=upload_path)


def s3_retrieve(
    key_path: str, obj: StrOrParticipantOrStudy, raw_path: bool = False, number_retries=3
) -> bytes:
    """ Takes an S3 file path (key_path), and a study ID.  Takes an optional argument, raw_path,
    which defaults to false.  When set to false the path is prepended to place the file in the
    appropriate study_id folder. """
    if not raw_path:
        key_path = s3_construct_study_key_path(key_path, obj)
    encrypted_data = _do_retrieve(S3_BUCKET, key_path, number_retries=number_retries)['Body'].read()
    assert S3_BUCKET is not Exception, "libs.s3.s3_retrieve called inside test"
    return decrypt_server(encrypted_data, smart_get_study_encryption_key(obj))


def s3_retrieve_plaintext(key_path: str, number_retries=3) -> bytes:
    """ Retrieves a file as-is as bytes. """
    return _do_retrieve(S3_BUCKET, key_path, number_retries=number_retries)['Body'].read()


def _do_retrieve(bucket_name: str, key_path: str, number_retries=3):
    """ Run-logic to do a data retrieval for a file in an S3 bucket."""
    assert S3_BUCKET is not Exception, "libs.s3._s3_retrieve(!!!) called inside test"
    try:
        return conn.get_object(Bucket=bucket_name, Key=key_path, ResponseContentType='string')
    except Exception as boto_error_unknowable_type:
        # Some error types cannot be imported because they are generated at runtime through a factory
        if boto_error_unknowable_type.__class__.__name__ == "NoSuchKey":
            raise NoSuchKeyException(f"{bucket_name}: {key_path}")
        # usually we want to try again
        if number_retries > 0:
            print("s3_retrieve failed, retrying on %s" % key_path)
            return _do_retrieve(bucket_name, key_path, number_retries=number_retries - 1)
        # unknown cases: explode.
        raise


def s3_list_files(prefix: str, as_generator=False) -> List[str]:
    """ Lists s3 keys matching prefix. as generator returns a generator instead of a list.
    WARNING: passing in an empty string can be dangerous. """
    assert S3_BUCKET is not Exception, "libs.s3.s3_list_files called inside test"
    return _do_list_files(S3_BUCKET, prefix, as_generator=as_generator)


def smart_s3_list_study_files(prefix: str, obj: StrOrParticipantOrStudy):
    """ Lists s3 keys matching prefix, autoinserting the study object id at start of key path. """
    assert S3_BUCKET is not Exception, "libs.s3.smart_s3_list_study_files called inside test"
    return s3_list_files(s3_construct_study_key_path(prefix, obj))


# just fyi this is not actually tested?  Please delete this comment if you know it works.
def smart_s3_list_chunked_files(prefix: str, obj: StrOrParticipantOrStudy):
    """ Lists s3 keys matching prefix, autoinserting the study object id at start of key path. """
    assert S3_BUCKET is not Exception, "libs.s3.smart_s3_list_study_files called inside test"
    return s3_list_files(f"{CHUNKS_FOLDER}/{s3_construct_study_key_path(prefix, obj)}")


def _do_list_files(bucket_name: str, prefix: str, as_generator=False) -> List[str]:
    paginator = conn.get_paginator('list_objects_v2')
    assert S3_BUCKET is not Exception, "libs.s3.__s3_list_files(!!!) called inside test"
    page_iterator: Paginator = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
    if as_generator:
        return _do_list_files_generator(page_iterator)
    
    items = []
    for page in page_iterator:
        if 'Contents' in page:
            for item in page['Contents']:
                items.append(item['Key'].strip("/"))
    return items


def _do_list_files_generator(page_iterator: Paginator):
    for page in page_iterator:
        if 'Contents' not in page:
            return
        for item in page['Contents']:
            yield item['Key'].strip("/")


#fixme: we have two s3_delete functions, we need to merge the class above with... participant deletion I think.
def s3_delete1(s3_path: str, obj: StrOrParticipantOrStudy, raw_path=True):
    if not raw_path:
        s3_path = s3_construct_study_key_path(s3_path, obj)
    conn.delete_object(Bucket=S3_BUCKET, Key=s3_path)


# todo: test
def s3_delete2(key_path: str) -> bool:
    assert S3_BUCKET is not Exception, "libs.s3.s3_delete called inside test"
    resp = conn.delete_object(Bucket=S3_BUCKET, Key=key_path)
    if not resp["DeleteMarker"]:
        raise Exception(f"Failed to delete {resp['Key']} version {resp['VersionId']}")
    return resp["DeleteMarker"]


# todo: test
def s3_delete_versioned(key_path: str, version_id: str) -> bool:
    assert S3_BUCKET is not Exception, "libs.s3.s3_delete_versioned called inside test"
    resp = conn.delete_object(Bucket=S3_BUCKET, Key=key_path, VersionId=version_id)
    if not resp["DeleteMarker"]:
        raise Exception(f"Failed to delete {resp['Key']} version {resp['VersionId']}")
    return resp["DeleteMarker"]


# todo: test
def s3_delete_many_versioned(paths_version_ids: List[Tuple[str, str]]):
    """ Takes a list of (key_path, version_id) tuples and deletes them all using the boto3
    delete_objects API.  Returns the number of files deleted, raises errors with reasonable
    clarity inside an errorhandler bundled error. """
    assert S3_BUCKET is not Exception, "libs.s3.s3_delete_many_versioned called inside test"
    error_handler = ErrorHandler()  # use an ErrorHandler to bundle up all errors and raise them at the end.
    
    # construct the usual insane boto3 dict - if version id is falsey, it must be a string, not None.
    if not paths_version_ids:
        raise Exception("s3_delete_many_versioned called with no paths.")
    
    delete_params = {
        'Objects': [{'Key': key_path, 'VersionId': version_id or "null"}
                    for key_path, version_id in paths_version_ids]
    }
    resp = conn.delete_objects(Bucket=S3_BUCKET, Delete=delete_params)
    deleted = resp['Deleted'] if "Deleted" in resp else []
    errors = resp['Errors'] if 'Errors' in resp else []
    
    # make legible error messages, bundle them up
    for e in errors:
        with error_handler:
            raise Exception(
                f"Error trying to delete {e['Key']} version {e['VersionId']}: {e['Code']} - {e['Message']}"
            )
    if resp['ResponseMetadata']['HTTPStatusCode'] != 200:
        with error_handler:
            raise Exception(f"HTTP status code {resp['ResponseMetadata']['HTTPStatusCode']} from s3.delete_objects")
    if 'Deleted' not in resp:
        with error_handler:
            raise Exception("No Deleted key in response from s3.delete_objects")
    
    error_handler.raise_errors()
    return len(deleted)  # will always error above if empty, cannot return 0.


def s3_list_versions(prefix: str) -> Generator[Tuple[str, Optional[str]], None, None]:
    """ Generator of all matching key paths and their version ids.  Performance in unpredictable, it
    is based on the historical presence of key paths matching the prefix, it is paginated, but we
    don't care about deletion markers """
    
    assert S3_BUCKET is not Exception, "libs.s3.s3_list_versions called inside test"
    for page in conn.get_paginator('list_object_versions').paginate(Bucket=S3_BUCKET, Prefix=prefix):
        # Page structure - each page is a dictionary with these keys:
        #    Name, ResponseMetadata, Versions, MaxKeys, Prefix, KeyMarker, IsTruncated, VersionIdMarker
        # We only care about 'Versions', which is a list of all object versions matching that prefix.
        # Versions is a list of dictionaries with these keys:
        #    LastModified, VersionId, ETag, StorageClass, Key, Owner, IsLatest, Size
        ## If versions is not present that means the entry is a deletion marker and can be skipped.
        if 'Versions' not in page:
            continue
        
        for s3_version in page['Versions']:
            # If versioning is disabled on the bucket then version id is "null", otherwise it will
            # be a real value. (Literally:  {'VersionId': 'null', 'Key': 'BEAUREGARD', ...}  )
            version = s3_version['VersionId']
            if version == "null":  # clean it up, no "null" strings, no INSANE boto formatting
                version = None
            yield s3_version['Key'], version


################################################################################
######################### Client Key Management ################################
################################################################################


def create_client_key_pair(patient_id: str, study_id: str):
    """Generate key pairing, push to database, return sanitized key for client."""
    public, private = generate_key_pairing()
    s3_upload("keys/" + patient_id + "_private", private, study_id)
    s3_upload("keys/" + patient_id + "_public", public, study_id)


def get_client_public_key_string(patient_id: str, study_id: str) -> str:
    """Grabs a user's public key string from s3."""
    key_string = s3_retrieve("keys/" + patient_id + "_public", study_id)
    return prepare_X509_key_for_java(key_string).decode()


def get_client_public_key(patient_id: str, study_id: str) -> RSA.RsaKey:
    """Grabs a user's public key file from s3."""
    key = s3_retrieve("keys/" + patient_id + "_public", study_id)
    return get_RSA_cipher(key)


def get_client_private_key(patient_id: str, study_id: str) -> RSA.RsaKey:
    """Grabs a user's private key file from s3."""
    key = s3_retrieve("keys/" + patient_id + "_private", study_id)
    return get_RSA_cipher(key)


###############################################################################
""" Research on getting a stream into the decryption code of pycryptodome

The StreamingBody StreamingBody object does not define the __len__ function, which is
necessary for creating a buffer somewhere in the decryption code, but it is possible to monkeypatch
it in like this:
    import botocore.response
    def monkeypatch_len(self):
        return int(self._content_length)
    botocore.response.StreamingBody.__len__ = monkeypatch_len

But that just results in this error from pycryptodome:
TypeError: Object type <class 'botocore.response.StreamingBody'> cannot be passed to C code """
