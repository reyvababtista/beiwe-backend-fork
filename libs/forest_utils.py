from __future__ import annotations

import pickle
from posixpath import join as path_join

from constants.common_constants import BEIWE_PROJECT_ROOT


# this is a hack to avoid circular imports but still use them for type hints
try:
    from database.forest_models import ForestTask
except ImportError:
    pass


# Cached data set serialization for Jasmine
def get_jasmine_all_bv_set_dict(task: ForestTask) -> dict:
    """ Return the unpickled all_bv_set dict. """
    from libs.s3 import s3_retrieve
    if not task.all_bv_set_s3_key:
        return None  # Forest expects None if it doesn't exist
    return pickle.loads(
        s3_retrieve(task.all_bv_set_s3_key, task.participant.study.object_id, raw_path=True)
    )


def get_jasmine_all_memory_dict_dict(task: ForestTask) -> dict:
    """ Return the unpickled all_memory_dict dict. """
    from libs.s3 import s3_retrieve
    if not task.all_memory_dict_s3_key:
        return None  # Forest expects None if it doesn't exist
    return pickle.loads(
        s3_retrieve(task.all_memory_dict_s3_key, task.participant.study.object_id, raw_path=True)
    )


def save_all_bv_set_bytes(task: ForestTask, all_bv_set_bytes):
    from libs.s3 import s3_upload
    task.all_bv_set_s3_key = task.all_bv_set_s3_key_path
    s3_upload(task.all_bv_set_s3_key, all_bv_set_bytes, task.participant, raw_path=True)
    task.save(update_fields=["all_bv_set_s3_key"])


def save_all_memory_dict_bytes(task: ForestTask, all_memory_dict_bytes):
    from libs.s3 import s3_upload
    task.all_memory_dict_s3_key = task.all_memory_dict_s3_key_path
    s3_upload(task.all_memory_dict_s3_key, all_memory_dict_bytes, task.participant, raw_path=True)
    task.save(update_fields=["all_memory_dict_s3_key"])


def save_output_file(task: ForestTask, output_file_bytes):
    from libs.s3 import s3_upload
    # output_zip_s3_path includes the study id, so we can use raw path
    s3_upload(task.output_zip_s3_path, output_file_bytes, task.participant, raw_path=True)
    task.save(update_fields=["output_zip_s3_path"])  # its already committed to the database


def download_output_file(task: ForestTask) -> bytes:
    from libs.s3 import s3_retrieve
    return s3_retrieve(task.output_zip_s3_path, task.participant, raw_path=True)


# our extremely fragile mechanism to get the git commit of the "current" forest version
def get_forest_git_hash() -> str:
    that_git_prefix = "git+https://git@github.com/onnela-lab/forest@"
    
    with open(path_join(BEIWE_PROJECT_ROOT, "requirements_data_processing.txt"), "rt") as f:
        requirements_file_lines = f.read().splitlines()
    
    git_version = ""
    for line in requirements_file_lines:
        # in the insane case of multiple matches we are getting the first instance, not the last.
        if line.startswith(that_git_prefix):
            git_version = line.split(that_git_prefix)[-1]
            break
    return git_version
