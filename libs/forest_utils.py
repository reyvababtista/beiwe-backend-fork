from __future__ import annotations

import pickle

# this is a hack to avoid circular imports but still use them for type hints
try:
    from database.forest_models import ForestTask
except ImportError:
    pass

# Cached data sets for Jasmine


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
