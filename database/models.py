# This file needs to populate all the other models in order for django to identify that it has
# all the models

from .common_models import *
from .study_models import *
from .survey_models import *
from .user_models import *
from .profiling_models import *
from .data_access_models import *
from .dashboard_models import *
from .schedule_models import *
from .system_models import *
from .tableau_api_models import *
from database.security_models import *

from django.core.validators import ProhibitNullCharactersValidator
from django.db.models.base import ModelBase
from django.db.models import fields


# dynamically inject the ProhibitNullCharactersValidator validator on all char and text fields.
# This takes about 1 millisecond (yuck, it changes size on iteration)
for name, database_model in [(k, v) for k, v in vars().items()]:
    if isinstance(database_model, ModelBase):
        for field in database_model._meta.fields:
            # print(name, field, type(field))
            if isinstance(field, (fields.CharField, fields.TextField)):
                if ProhibitNullCharactersValidator not in field.validators:
                    field.validators.append(ProhibitNullCharactersValidator())
