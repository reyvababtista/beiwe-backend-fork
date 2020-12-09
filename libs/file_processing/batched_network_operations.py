import sys
import traceback
from typing import Tuple

from database.data_access_models import ChunkRegistry
from libs.file_processing.utility_functions_simple import decompress
from libs.s3 import s3_upload

# from datetime import datetime
# GLOBAL_TIMESTAMP = datetime.now().isoformat()


def batch_upload(upload: Tuple[ChunkRegistry, str, bytes, str]):
    """ Used for mapping an s3_upload function.  the tuple is unpacked, can only have one parameter. """
    ret = {'exception': None, 'traceback': None}
    try:
        chunk, chunk_path, new_contents, study_object_id = upload
        del upload
        new_contents = decompress(new_contents)

        if "b'" in chunk_path:
            raise Exception(chunk_path)

        # for use with test script to avoid network uploads
        # with open("processing_tests/" + GLOBAL_TIMESTAMP, 'ba') as f:
        #     f.write(b"\n\n")
        #     f.write(new_contents)
        #     return ret

        s3_upload(chunk_path, new_contents, study_object_id, raw_path=True)

        if chunk.pk and chunk.pk != 0:
            # If the contents are being appended to an existing ChunkRegistry object
            chunk.file_size = len(new_contents)
            chunk.update_chunk(new_contents)

        else:
            # We actually have some complex stuff to do to instantiate, so we pass variables
            # into the specialized constructor rather than use the object directly.  (weird)
            ChunkRegistry.register_chunked_data(
                chunk.data_type,
                chunk.time_bin,
                chunk.chunk_path,
                new_contents,
                chunk.study.pk,
                chunk.participant.pk,
                chunk.survey.pk,
            )

    # it broke. print stacktrace for debugging
    except Exception as e:
        traceback.print_exc()
        ret['traceback'] = sys.exc_info()
        ret['exception'] = e

    return ret
