import base64
import codecs
import hashlib
import io
import random
from binascii import Error as base64_error
from os import urandom
from typing import Tuple

import pyotp
import pyqrcode

from constants.security_constants import BASE64_GENERIC_ALLOWED_CHARACTERS, EASY_ALPHANUMERIC_CHARS


# Custom Error Classes
class DatabaseIsDownError(Exception): pass
class PaddingException(Exception): pass
class Base64LengthException(Exception): pass
class SecurityError(Exception): pass
class BadDjangoKeyFormatting(Exception): pass


################################################################################
################################### Base64 #####################################
################################################################################

def encode_generic_base64(data: bytes) -> bytes:
    """ Creates a url safe base64 representation of an input string, strips all new lines. """
    return base64.b64encode(data).replace(b"\n", b"")


def encode_base64(data: bytes) -> bytes:
    """ Creates a base64 representation of an input string, strips all new lines. """
    return base64.urlsafe_b64encode(data).replace(b"\n", b"")


def decode_base64(data: bytes, paddiing_fix=0) -> bytes:
    """ unpacks url safe base64 encoded string. Throws a more obviously named variable when
    encountering a padding error, which just means that there was no base64 padding for base64
    blobs of invalid length (possibly invalid base64 ending characters). """
    try:
        return base64.urlsafe_b64decode(data)
    except base64_error as e:
        # (in python 3.8 the error message is changed to include this information.)
        length = len(data.strip(b"="))
        if length % 4 != 0:
            # stacktrace readers: this means corrupted data.
            raise Base64LengthException(
                f"Data provided had invalid length {length} after padding was removed."
            )
        
        if "incorrect padding" in str(e).lower() or "number of data characters" in str(e).lower():
            # for unknown reasons sometimes the padding is wrong, probably on corrupted data.
            # Character counts supposed to be divisible by 4. recurring because its easy.
            if paddiing_fix <= 4:
                paddiing_fix += 1
                padding = b"=" * paddiing_fix
                return decode_base64(data + padding, paddiing_fix=paddiing_fix)
            # str(data) here is correct, we need a representation of the data, not the raw data.
            raise PaddingException(f'{str(e)} -- "{str(data)}"')
        
        raise  # preserves original stacktrace


################################################################################
################################## HASHING #####################################
################################################################################

# noinspection InsecureHash
def chunk_hash(data: bytes) -> bytes:
    """ We need to hash data in a data stream chunk and store the hash in mongo. """
    digest = hashlib.md5(data).digest()
    return codecs.encode(digest, "base64").replace(b"\n", b"")


# noinspection InsecureHash
def device_hash(data: bytes) -> bytes:
    """ Hashes an input string using the sha256 hash, mimicking the hash used on
    the devices.  Expects a string not in base64, returns a base64 string."""
    sha256 = hashlib.sha256()
    sha256.update(data)
    return encode_base64(sha256.digest())


################################################################################
################################## Passwords ###################################
################################################################################

def django_password_components(password: str) -> Tuple[str, int, bytes, bytes]:
    """ In anticipation of adopting the django user model we are adopting the django password format.
    https://docs.djangoproject.com/en/4.1/topics/auth/passwords/ """
    try:
        algorithm, iterations, password, salt = password.split("$")
    except ValueError as e:
        raise BadDjangoKeyFormatting(str(e))
    return algorithm, int(iterations), password.encode(), salt.encode()


def to_django_password_components(algorithm: str, iterations: int, password_hash: bytes, salt: bytes) -> str:
    return f"{algorithm}${iterations}${password_hash.decode()}${salt.decode()}"


def generate_hash_and_salt(algorithm: str, iterations: int, password: bytes) -> Tuple[bytes, bytes]:
    """ Generates a hash and salt that will match for a given input string based on the algorithm
    and iteration count. """
    if not isinstance(password, bytes):
        raise TypeError("invalid password, password must be a byte string.")
    salt = encode_base64(urandom(16 if algorithm in ('sha1', 'sha256') else 32))
    password_hashed = password_hash(algorithm, iterations, password, salt)
    return password_hashed, salt


def compare_password(
    algorithm: str, iterations: int, proposed_password: bytes, real_password_hash: bytes, salt: bytes,
) -> bool:
    """ Compares a proposed password with a salt and a real password, returns
        True if the hash results are identical.
        Expects the proposed password to be a base64 encoded string.
        Expects the real password to be a base64 encoded string. """
    # password_hash returns a base64 representation, this is fine, we don't need to de-base64.
    return real_password_hash == password_hash(algorithm, iterations, proposed_password, salt)


def password_hash(algorithm: str, iterations: int, proposed_password: bytes, salt: bytes) -> bytes:
    # These are the only algorithms we accept, for some reason django doesn't actually have sha512
    # built-in, but we are prepared for future longer dklen sizes.
    if algorithm not in ('sha1', 'sha256', 'sha512'):
        raise SecurityError(f"password hashing received undocumented algorithm: '{algorithm}'")
    # we are not going to allow None or 0 defaults, if they even exist. Custom error is better.
    if not iterations:
        raise SecurityError(f"password hashing received invalid iterations: '{iterations}'")
    dklen = 32 if algorithm in ('sha1', 'sha256') else 64
    return encode_base64(hashlib.pbkdf2_hmac(algorithm, proposed_password, salt, iterations, dklen))


################################################################################
############################### Random #########################################
################################################################################
# Seed the random number subsystem with some good entropy.
# This is a security measure, it happens once at import-time, don't remove it.
random.seed(urandom(256))


def generate_easy_alphanumeric_string(length: int = 8) -> str:
    """ Generates an "easy" alphanumeric (lower case) string of length 8 without the 0 (zero)
    character. This is a design decision, because users will have to type in the "easy" string on
    mobile devices, so we have made this a string that is easy to type and easy to distinguish the
    characters of (e.g. no I/l, 0/o/O confusion). """
    return ''.join(random.choice(EASY_ALPHANUMERIC_CHARS) for _ in range(length))


def generate_random_string(length: int) -> str:
    """ Generates a random string of base64 characters. """
    return ''.join(random.choice(BASE64_GENERIC_ALLOWED_CHARACTERS) for _ in range(length))


def generate_random_bytestring(length: int) -> bytes:
    """ Generates a random string of base64 characters as a bytes. """
    return ''.join(random.choice(BASE64_GENERIC_ALLOWED_CHARACTERS) for _ in range(length)).encode()


################################################################################
#################################### MFA #######################################
################################################################################


def qrcode_bas64_png(url: str) -> str:
    """ Takes a url and produces a base64 encoded png of a QR code, suitable for embedding in an
    html page using the pyqrcode library. """
    qr_code = pyqrcode.create(url, error="L")  # set error correction to low for smaller qr
    buffer = io.BytesIO()
    qr_code.png(buffer, scale=6)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode()


def verify_mfa(mfa_token: str, code_to_test: str) -> bool:
    """ Returns a string of the current OTP code for the given secret. """
    # window is the number of future and past codes to include in the  check.
    return create_mfa_object(mfa_token).verify(code_to_test, valid_window=1)


def create_mfa_object(mfa_token: str) -> pyotp.TOTP:
    """ Creates a one time password object with some defaults so that it is documented how we are
    configuring this. The digest is the hash algorithm, the default is sha1 so we override that on
    principle (its considered generally insecure). """
    return pyotp.TOTP(
        mfa_token,
        digits=6,
        digest=hashlib.sha512,
        name=None,
        issuer=None,
        interval=30,
    )


def get_current_mfa_code(mfa_token: str) -> str:
    """ Returns a string of the current OTP code for the given secret, primarily for debugging. """
    return create_mfa_object(mfa_token).now()
