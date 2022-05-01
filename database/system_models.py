from django.db import models

from database.common_models import TimestampedModel


class FileAsText(TimestampedModel):
    tag = models.CharField(null=False, blank=False, max_length=256, db_index=True)
    text = models.TextField(null=False, blank=False)
