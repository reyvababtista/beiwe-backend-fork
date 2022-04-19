import json
import traceback
from typing import List

from Cryptodome.Cipher import AES

from config.settings import STORE_DECRYPTION_KEY_ERRORS, STORE_DECRYPTION_LINE_ERRORS
from constants.participant_constants import IOS_API
from constants.security_constants import URLSAFE_BASE64_CHARACTERS
from database.data_access_models import IOSEDecryptionKey
from database.profiling_models import (DecryptionKeyError, EncryptionErrorMetadata,
    LineEncryptionError)
from database.user_models import Participant
from libs.security import Base64LengthException, decode_base64, encode_base64, PaddingException


class DecryptionKeyInvalidError(Exception): pass
class HandledError(Exception): pass
# class UnHandledError(Exception): pass  # for debugging
class InvalidIV(Exception): pass
class InvalidData(Exception): pass
class DefinitelyInvalidFile(Exception): pass


# TODO: there is a circular import due to the database imports in this file and this file being
# imported in s3, forcing local s3 imports in various files.  Refactor and fix.


########################### User/Device Decryption #############################


class DeviceDataDecryptor():
    
    def __init__(self, file_name: str, original_data: bytes, participant: Participant) -> None:
        # basic info
        self.file_name: str = file_name
        self.original_data: bytes = original_data
        self.participant: Participant = participant
        
        # storage and error tracking
        self.bad_lines: List[bytes] = []
        self.error_types: List[str] = []
        self.good_lines: List[bytes] = []
        self.error_count = 0
        
        # decryption key extraction
        self.private_key_cipher = self.participant.get_private_key()
        self.file_data = self.split_file()
        self.aes_decryption_key = self.extract_aes_key()
        
        # join should be rather well optimized and not cause O(n^2) total memory copies
        self.file_data = b"\n".join(self.good_lines)
        
        # line index is index to files_list variable of the current line
        self.line_index = None
    
    def split_file(self) -> List[bytes]:
        # don't refactor to pop the decryption key line out of the file_data list, this list
        # can be thousands of lines.  Also, this line is a 2x memcopy with N new bytes objects.
        file_data = [line for line in self.original_data.split(b'\n') if line != b""]
        if not file_data:
            raise HandledError("The file had no data in it.  Return 200 to delete file from device.")
        return file_data
    
    def decrypt_device_file(self) -> bytes:
        """ Runs the line-by-line decryption of a file encrypted by a device. """
        # we need to skip the first line (the decryption key), but need real index values in i
        lines = enumerate(self.file_data)
        next(lines)
        for line_index, line in lines:
            self.line_index = line_index
            if line is None:
                # this case causes weird behavior inside decrypt_device_line, so we test for it instead.
                self.error_count += 1
                self.append_line_encryption_error(LineEncryptionError.LINE_IS_NONE, line)
                # print("encountered empty line of data, ignoring.")
                continue
            try:
                self.good_lines.append(self.decrypt_device_line(line))
            except Exception as error_orig:
                self.handle_line_error(line, error_orig)
        self.create_metadata_error()
    
    def extract_aes_key(self) -> bytes:
        # The following code is ... strange because of an unfortunate design design decision made
        # quite some time ago: the decryption key is encoded as base64 twice, once wrapping the
        # output of the RSA encryption, and once wrapping the AES decryption key.  This happened
        # because I was not an experienced developer at the time, python2's unified string-bytes
        # class didn't exactly help, and java io is... java io.
        
        try:
            key_base64_raw: bytes = self.file_data[0]
            # print(f"key_base64_raw: {key_base64_raw}")
        except IndexError:
            # probably not reachable due to test for emptiness prior in code; keep just in case...
            self.create_decryption_key_error(traceback.format_exc())
            raise DecryptionKeyInvalidError("There was no decryption key.")
        
        # Test that every "character" (they are 8 bit bytes) in the byte-string of the raw key is
        # a valid url-safe base64 character, this will cut out certain junk files too.
        for c in key_base64_raw:
            if c not in URLSAFE_BASE64_CHARACTERS:
                # need a stack trace....
                try:
                    raise DecryptionKeyInvalidError(f"Decryption key not base64 encoded: {key_base64_raw}")
                except DecryptionKeyInvalidError:
                    self.create_decryption_key_error(traceback.format_exc())
                    raise
        
        # handle the various cases that can occur when extracting from base64.
        try:
            decoded_key: bytes = decode_base64(key_base64_raw)
            # print(f"decoded_key: {decoded_key}")
        except (TypeError, PaddingException, Base64LengthException) as decode_error:
            self.create_decryption_key_error(traceback.format_exc())
            raise DecryptionKeyInvalidError(f"Invalid decryption key: {decode_error}")
        
        try:
            base64_key: bytes = self.private_key_cipher.decrypt(decoded_key)
            # print(f"base64_key: {len(base64_key)} {base64_key}")
            decrypted_key = decode_base64(base64_key)
            # print(f"decrypted_key: {len(decrypted_key)} {decrypted_key}")
            if not decrypted_key:
                raise TypeError(f"decoded key was '{decrypted_key}'")
        except (TypeError, IndexError, PaddingException, Base64LengthException) as decr_error:
            self.create_decryption_key_error(traceback.format_exc())
            raise DecryptionKeyInvalidError(f"Invalid decryption key: {decr_error}")
        
        # If the decoded bits of the key is not exactly 128 bits (16 bytes) that probably means that
        # the RSA encryption failed - this occurs when the first byte of the encrypted blob is all
        # zeros.  Apps require an update to solve this (in a future rewrite we should use a padding
        # algorithm).
        if len(decrypted_key) != 16:
            # print(len(decrypted_key))
            # need a stack trace....
            try:
                raise DecryptionKeyInvalidError(f"Decryption key not 128 bits: {decrypted_key}")
            except DecryptionKeyInvalidError:
                self.create_decryption_key_error(traceback.format_exc())
                raise
        
        # iOS has a bug where the file gets split into two uploads, so the second one is missing a
        # decryption key. We store iOS decryption keys. and use them for those files - because the
        # ios app "resists analysis" (its bad. its just bad.)
        if self.participant.os_type == IOS_API:
            IOSEDecryptionKey.objects.create(
                s3_file_path=self.file_name.replace("_", "/"),  # mimic naming convention for FileToProcess
                base64_encryption_key=base64_key.decode(),
                participant=self.participant,
            )
        
        return decrypted_key
    
    def decrypt_device_line(self, base64_data: bytes) -> bytes:
        """ Config (the file and its iv; why I named it that is a mystery) is expected to be 3 colon
            separated values.
            value 1 is the symmetric key, encrypted with the patient's public key.
            value 2 is the initialization vector for the AES CBC cipher.
            value 3 is the config, encrypted using AES CBC, with the provided key and iv. """
        iv, base64_data = base64_data.split(b":")
        iv = decode_base64(iv)
        data = decode_base64(data)
        
        # handle cases of no data, and less than 16 bytes of data, which is an equivalent scenario.
        if not data or len(data) < 16:
            raise InvalidData()
        if not iv or len(iv) < 16:
            raise InvalidIV()
        
        # CBC data encryption requires alignment to a 16 bytes, we lose any data that overflows that length.
        overflow_bytes = len(data) % 16
        
        if overflow_bytes:
            # print("\n\nFOUND OVERFLOWED DATA\n\n")
            # print("device os:", self.participant.os_type)
            # print("\n\n")
            data = data[:-overflow_bytes]
        
        try:
            decipherer = AES.new(self.aes_decryption_key, mode=AES.MODE_CBC, IV=iv)
            decrypted = decipherer.decrypt(data)
        except Exception:
            if iv is None:
                len_iv = "None"
            else:
                len_iv = len(iv)
            if data is None:
                len_data = "None"
            else:
                len_data = len(data)
            if self.aes_decryption_key is None:
                len_key = "None"
            else:
                len_key = len(self.aes_decryption_key)
            # these print statements cause problems in getting encryption errors because the print
            # statement will print to an ascii formatted log file on the server, which causes
            # ascii encoding error.  Enable them for debugging only. (leave uncommented for Sentry.)
            # print("length iv: %s, length data: %s, length key: %s" % (len_iv, len_data, len_key))
            # print('%s %s %s' % (patient_id, key, orig_data))
            raise
        
        # PKCS5 Padding: The last byte of the byte-string contains the number of bytes at the end of the
        # bytestring that are padding.  As string slicing in python are a copy operation we will
        # detect the fast-path case of no change so that we can skip it
        num_padding_bytes = decrypted[-1]
        if num_padding_bytes:
            decrypted = decrypted[0: -num_padding_bytes]
        return decrypted
    
    def handle_line_error(self, line: bytes, error: Exception):
        error_string: str(error)
        this_error_message = "There was an error in user decryption: "
        self.error_count += 1
        
        if isinstance(error, (Base64LengthException, PaddingException)):
            # this case used to also catch IndexError, this probably changed after python3 upgrade
            this_error_message += "Something is wrong with data padding:\n\tline: %s" % line
            self.append_line_encryption_error(line, LineEncryptionError.PADDING_ERROR)
        # TODO: untested, error should be caught as a decryption key error
        elif isinstance(error, ValueError) and "Key cannot be the null string" in error_string:
            this_error_message += "The key was the null string:\n\tline: %s" % line
            self.append_line_encryption_error(line, LineEncryptionError.EMPTY_KEY)
        
        ################### skip these errors ##############################
        elif "unpack" in error_string:
            # the config is not colon separated correctly, this is a single line error, we can just
            # drop it. implies an interrupted write operation (or read)
            this_error_message += "malformed line of config, dropping it and continuing."
            self.append_line_encryption_error(line, LineEncryptionError.MALFORMED_CONFIG)
        elif isinstance(error, InvalidData):
            this_error_message += "Line contained no data, skipping: " + str(line)
            self.append_line_encryption_error(line, LineEncryptionError.LINE_EMPTY)
        
        # this break in the error catching is preserved. why do we do this? multiple errors in one pass?>
        if isinstance(error, InvalidIV):
            this_error_message += "Line contained no iv, skipping: " + str(line)
            self.append_line_encryption_error(line, LineEncryptionError.IV_MISSING)
        elif "Incorrect IV length" in error_string or 'IV must be' in error_string:
            # shifted this to an okay-to-proceed line error March 2021
            # Jan 2022: encountered pycryptodome form: "Incorrect IV length"
            this_error_message += "iv has bad length."
            self.append_line_encryption_error(line, LineEncryptionError.IV_BAD_LENGTH)
        elif 'Incorrect padding' in error_string:
            this_error_message += "base64 padding error, config is truncated."
            self.append_line_encryption_error(line, LineEncryptionError.MP4_PADDING)
            # this is only seen in mp4 files. possibilities: upload during write operation. broken
            #  base64 conversion in the app some unanticipated error in the file upload
            raise HandledError(this_error_message)
        else:
            # If none of the above errors happened, raise the error raw
            raise error
    
    def append_line_encryption_error(self, line: bytes, error_type: str, index):
        # handle creating line orrers
        self.error_types.append(error_type)
        self.bad_lines.append(line)
        i = self.line_index
        
        # declaring this inside decrypt device file to access its function-global variables
        if STORE_DECRYPTION_LINE_ERRORS:
            LineEncryptionError.objects.create(
                type=error_type,
                base64_decryption_key=encode_base64(self.aes_decryption_key),
                line=encode_base64(line),
                prev_line=self.file_data[i - 1] if i > 0 else '',
                next_line=self.file_data[i + 1] if i < len(self.file_data) - 1 else '',
                participant=self.participant,
            )
    
    def create_metadata_error(self):
        if self.error_count:
            EncryptionErrorMetadata.objects.create(
                file_name=self.file_name,
                total_lines=len(self.file_data),
                number_errors=self.error_count,
                # generator comprehension:
                error_lines=json.dumps((str(line for line in self.bad_lines))),
                error_types=json.dumps(self.error_types),
                participant=self.participant,
            )
    
    def create_decryption_key_error(self, an_traceback: str):
        # helper function with local variable access.
        # do not refactor to include raising the error in this function, that obfuscates the source.
        if STORE_DECRYPTION_KEY_ERRORS:
            DecryptionKeyError.do_create(
                file_path=self.file_name,
                contents=self.original_data,
                traceback=an_traceback,
                participant=self.participant,
            )
