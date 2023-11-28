from __future__ import annotations

import traceback

from django.db import models

from database.common_models import TimestampedModel


class FileAsText(TimestampedModel):
    tag = models.CharField(null=False, blank=False, max_length=256, db_index=True)
    text = models.TextField(null=False, blank=False)


class GenericEvent(TimestampedModel):
    tag = models.CharField(null=False, blank=False, max_length=256, db_index=True)
    note = models.TextField(null=False, blank=False)
    stacktrace = models.TextField(null=True, blank=True)
    
    @classmethod
    def easy_create(cls, tag: str, note: str):
        # this gets a list of the current stack trace, we just need to remove the last one to get
        # the stack trace for the caller of easy_create.
        tb: list = traceback.format_list(traceback.extract_stack())[:-2]
        GenericEvent.objects.create(tag=tag, note=note, stacktrace="".join(tb))


class SingletonModel(TimestampedModel):
    """ A model that destructively maintains exactly one instance. Be very careful with these
    models. """
    class Meta:
        abstract = True
    
    @classmethod
    def get_singleton_instance(cls):
        """ An objectively dumb way of making sure we only ever have one of these. """
        count = cls.objects.count()
        if count > 1:
            exclude = cls.objects.order_by("created_on").first().id
            cls.objects.exclude(id=exclude).delete()
            return cls.get_singleton_instance()
        if count == 0:
            ret = cls()
            ret.save()
            return ret
        # if count == 1:  # guaranteed
        return cls.objects.first()


# todo: make this part of GlobalSettings?
# used and updated in update_forest_versions script for display on the forest page
class ForestVersion(SingletonModel):
    """ Singleton model that holds the version of the forest package and it's git commit hash. """
    package_version = models.TextField(blank=True, null=False, default="")
    # should be a 40 character hash, until git decides its time to update to sha256.
    git_commit = models.TextField(blank=True, null=False, default="")


class GlobalSettings(SingletonModel):
    """ A singleton model that holds global settings for the entire website, and for the data
    processing server(s). """
    
    # see the downtime middleware.
    downtime_enabled = models.BooleanField(default=False)