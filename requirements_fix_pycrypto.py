import os
import sys
from subprocess import check_call

try:
    import pytz
except ImportError:
    raise Exception("you need to run basic installs first")

"""
PyCrypto's install process involves running 2to3 on the codebase and a compile step. Starting no
earlier than python version 3.8.8, and no later than python 3.8.12, the 2to3 operation started to
fail.  In order to resolve this we need to manually patch the library. This is needed for general
deploy as well, and is handled in the deployment code.

This script runs the same operation on your local python package installs.

We can remove this code when we upgrade the apps to use non-RSA based encypherment of AES encryption
keys, this requires app and backend updates.

Decryption code (libs/encryption.py) was recently updated to allow changes to encryption code, at
time of writing this no work has been started in the apps.

Sorry for the hassle.
"""

# test python version
major, minor = sys.version_info[0:2]
if major != 3 or minor != 8:
    raise Exception(
        "this code expects python 3.8, if it is compatible with other versions please submit "
        "bug report at https://github.com/onnela-lab/beiwe-backend"
    )

# Identify the appropriate directory for the pycrypto patch, and the python site-packages folder.
# (there are no trailing slashes for either due to rsplit behavior)
SITE_PACKAGES: str = os.path.abspath(pytz.__file__.rsplit("/", 2)[0])
BEIWE_ROOT: str = os.path.abspath(__file__).rsplit("/", 1)[0]
tar_file = BEIWE_ROOT + "/cluster_management/pushed_files/crypto.tar.gz"
pycrypto_folder = SITE_PACKAGES + "/Crypto"

print(f"\nattempting to patch pycrypto at {pycrypto_folder}...\n")

# commnad should expand the tar file in-place, overwriting files in the folder.
tar_command = f"tar -xf {tar_file} -C {pycrypto_folder}"
print("running", tar_command, "...\n")

# RUN!
check_call(tar_command, shell=True)

try:
    from Crypto.PublicKey import RSA
    print("if you are seeing this message then the patch... WORKED!")
except ImportError:
    print("if you are seeing this message then the patch... FAILED!")
    print("if you with to submit a bug report at bug report at https://github.com/onnela-lab/beiwe-backend/issues")
    print("please include system os with as much version info as you can, virtual environment manager, and this python version string:")
    print(sys.version.replace("\n", " "))
