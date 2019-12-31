# This file needs to populate all the other models in order for django to identify that it has
# all the models
from collections import Counter

from .common_models import *
from .study_models import *
from .user_models import *
from .profiling_models import *
from .data_access_models import *
