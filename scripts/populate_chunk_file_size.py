from __future__ import print_function

from os.path import abspath as _abspath
from sys import path as _path
_one_folder_up = _abspath(__file__).rsplit('/',2)[0]
_path.insert(1, _one_folder_up)

from config import load_django
from datetime import datetime

from database.data_access_models import ChunkRegistry
from libs.s3 import conn, S3_BUCKET

print("start:", datetime.now())
query = ChunkRegistry.objects.filter(file_size__isnull=True).values_list("pk", "chunk_path")
for i, (pk, path) in enumerate(query):
    if i % 1000 == 0:
        print(i)
    size = conn.get_object(Bucket=S3_BUCKET, Key=path)["ContentLength"]
    ChunkRegistry.objects.filter(pk=pk).update(file_size=size)
print("end:", datetime.now())