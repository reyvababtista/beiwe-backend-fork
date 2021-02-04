# add the root of the project into the path to allow cd-ing into this folder and running the script.
from os.path import abspath
from sys import path

path.insert(0, abspath(__file__).rsplit('/', 2)[0])

from collections import Counter

from database.data_access_models import FileToProcess

files = Counter(FileToProcess.objects.values_list("s3_file_path", flat=True))

for path, count in files.items():
    if count > 1:
        pks = list(FileToProcess.objects.filter(s3_file_path=path).values_list("pk", flat=True))
        pks.pop(0)
        deleted_count = FileToProcess.objects.filter(pk__in=pks).delete()
        print(f"deleted {deleted_count} extra instances of {path}")
