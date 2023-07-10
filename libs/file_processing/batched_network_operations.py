import sys
import traceback
from typing import Tuple

from django.utils import timezone

from constants.data_processing_constants import CHUNK_EXISTS_CASE
from database.data_access_models import ChunkRegistry
from libs.file_processing.utility_functions_simple import decompress
from libs.s3 import s3_upload
from libs.security import chunk_hash
from libs.sentry import make_error_sentry, SentryTypes


# from datetime import datetime
# GLOBAL_TIMESTAMP = datetime.now().isoformat()


def batch_upload(upload: Tuple[ChunkRegistry or dict, str, bytes, str]):
    """ Used for mapping an s3_upload function.  the tuple is unpacked, can only have one parameter. """
    
    ret = {'exception': None, 'traceback': None}
    with make_error_sentry(sentry_type=SentryTypes.data_processing):
        try:
            chunk, chunk_path, new_contents, study_object_id = upload
            new_contents = decompress(new_contents)
            
            # for use with test script to avoid network uploads
            # with open("processing_tests/" + GLOBAL_TIMESTAMP, 'ba') as f:
            #     f.write(b"\n\n")
            #     f.write(new_contents)
            #     return ret
            
            if chunk != CHUNK_EXISTS_CASE and ChunkRegistry.objects.filter(chunk_path=chunk_path).exists():
                raise Exception(f"Chunk \"{chunk_path}\" created between processing start and now.")
            
            s3_upload(chunk_path, new_contents, study_object_id, raw_path=True)
            
            # if the chunk object is a chunk registry then we are updating an old one,
            # otherwise we are creating a new one.
            if chunk == CHUNK_EXISTS_CASE:
                # If the contents are being appended to an existing ChunkRegistry object
                ChunkRegistry.objects.filter(chunk_path=chunk_path).update(
                    file_size=len(new_contents),
                    chunk_hash=chunk_hash(new_contents).decode(),
                    last_updated=timezone.now()
                )
            else:
                ChunkRegistry.register_chunked_data(**chunk, file_contents=new_contents)
        
        # it broke. print stacktrace for debugging
        except Exception as e:
            traceback.print_exc()
            ret['traceback'] = sys.exc_info()
            ret['exception'] = e
            
            # using an error sentry we can easily report a real error with a real stack trace! :D
            raise
    
    return ret
