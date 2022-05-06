import traceback

from django.db import models

from database.common_models import TimestampedModel


class FileAsText(TimestampedModel):
    tag = models.CharField(null=False, blank=False, max_length=256, db_index=True)
    text = models.TextField(null=False, blank=False)


class GenericEvent(TimestampedModel):
    tag = tag = models.CharField(null=False, blank=False, max_length=256, db_index=True)
    note = models.TextField(null=False, blank=False)
    stacktrace = models.TextField(null=True, blank=True)
    
    @classmethod
    def easy_create(cls, tag: str, note: str):
        # this gets a list of the current stack trace, we just need to remove the last one to get
        # the stack trace for the caller of easy_create.
        tb: list = traceback.format_list(traceback.extract_stack())[:-2]
        GenericEvent.objects.create(tag=tag, note=note, stacktrace="".join(tb))
