DECRYPTION_KEY_ERROR_MESSAGE = "This file did not contain a valid decryption key and could not be processed."

DECRYPTION_KEY_ADDITIONAL_MESSAGE = "This is an open bug: github.com/onnela-lab/beiwe-backend/issues/186"

S3_FILE_PATH_UNIQUE_CONSTRAINT_ERROR = "File to process with this S3 file path already exists"

UNKNOWN_ERROR = "AN UNKNOWN ERROR OCCURRED."

INVALID_EXTENSION_ERROR = "contains an invalid extension, it was interpreted as "

NO_FILE_ERROR = "there was no provided file name, this is an app error."

EMPTY_FILE_ERROR = "there was no/an empty file, returning 200 OK so device deletes bad file."

DEVICE_IDENTIFIERS_HEADER = "patient_id,MAC,phone_number,device_id,device_os,os_version,product,brand,hardware_id,manufacturer,model,beiwe_version\n"

# this is a set of integers (bytes, technically), it is faster than testing bytes
URLSAFE_BASE64_CHARACTERS = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-=")
