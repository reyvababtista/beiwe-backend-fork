from os import urandom

from Cryptodome.Cipher import AES

from database.study_models import Study


def encrypt_for_server(input_string: bytes, study_object_id: str) -> bytes:
    """ Encrypts config using the ENCRYPTION_KEY, prepends the generated initialization vector.
    Use this function on an entire file (as a string). """
    if not isinstance(study_object_id, str):
        raise Exception(f"received non-string object {study_object_id}")
    encryption_key: bytes = Study.objects.get(object_id=study_object_id) \
        .values_list("encryption_key", flat=True).get().encode()  # bytes
    iv: bytes = urandom(16)  # bytes
    return iv + AES.new(encryption_key, AES.MODE_CFB, segment_size=8, IV=iv).encrypt(input_string)


def decrypt_server(data: bytes, study_object_id: str) -> bytes:
    """ Decrypts config encrypted by the encrypt_for_server function. """
    if not isinstance(study_object_id, str):
        raise TypeError(f"received non-string object {study_object_id}")
    
    encryption_key = Study.objects.filter(object_id=study_object_id) \
        .values_list('encryption_key', flat=True).get().encode()
    iv = data[:16]
    data = data[16:]  # gr arg, memcopy operation...
    return AES.new(encryption_key, AES.MODE_CFB, segment_size=8, IV=iv).decrypt(data)
