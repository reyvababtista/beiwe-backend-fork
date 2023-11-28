import os
from os.path import join

from django.core.exceptions import ImproperlyConfigured

from config import DB_MODE, DB_MODE_POSTGRES, DB_MODE_SQLITE
from config.settings import DOMAIN_NAME, FLASK_SECRET_KEY, SENTRY_ELASTIC_BEANSTALK_DSN
from constants.common_constants import BEIWE_PROJECT_ROOT
from libs.sentry import normalize_sentry_dsn


# SECRET KEY is required by the django management commands, using the flask key is fine because
# we are not actually using it in any server runtime capacity.
SECRET_KEY = FLASK_SECRET_KEY

if DB_MODE == DB_MODE_SQLITE:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': join(BEIWE_PROJECT_ROOT, "private/beiwe_db.sqlite"),
            'CONN_MAX_AGE': None,
            'TEST': {
                'NAME': join(BEIWE_PROJECT_ROOT, "private/beiwe_test_db.sqlite"),
            },
        },
    }
elif DB_MODE == DB_MODE_POSTGRES:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.environ['RDS_DB_NAME'],
            'USER': os.environ['RDS_USERNAME'],
            'PASSWORD': os.environ['RDS_PASSWORD'],
            'HOST': os.environ['RDS_HOSTNAME'],
            'CONN_MAX_AGE': 0,
            'OPTIONS': {'sslmode': 'require'},
            "ATOMIC_REQUESTS": True,  # default is True, just being explicit
            'TEST': {
                'MIGRATE': True,
            }
        },
    }
else:
    raise ImproperlyConfigured("server not running as expected, could not find environment variable DJANGO_DB_ENV")

# database primary key setting
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

DEBUG = 'localhost' in DOMAIN_NAME or '127.0.0.1' in DOMAIN_NAME or '::1' in DOMAIN_NAME

SECURE_SSL_REDIRECT = not DEBUG

MIDDLEWARE = [
    'middleware.downtime_middleware.DowntimeMiddleware',  # does a single database call
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    # 'django.middleware.csrf.CsrfViewMiddleware',
    # 'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'middleware.abort_middleware.AbortMiddleware',
    # "middleware.request_to_curl.CurlMiddleware",  # uncomment to enable a debugging tool
]

TIME_ZONE = 'UTC'
USE_TZ = True

INSTALLED_APPS = [
    'database.apps.DatabaseConfig',
    'django.contrib.sessions',
    'django_extensions',
    'timezone_field',
    'rest_framework',
    # 'static_files',
]

SHELL_PLUS = "ipython"

SHELL_PLUS_POST_IMPORTS = [
    # generic
    "json",
    "orjson",
    ["collections", ("Counter", "defaultdict")],
    ["pprint", ("pprint",)],
    
    # datetimezone
    "dateutil",  # do not add pytz it is deprecated
    ["dateutil", ('tz',)],
    ["dateutil.tz", ('UTC',)],
    ["time", ("sleep",)],
    ["datetime", ("date", "datetime", "timedelta", "tzinfo")],
    ["django.utils.timezone", ("localtime", "make_aware", "make_naive")],
    
    # shell
    ["libs.utils.shell_utils", "*"],
    ['libs.utils.dev_utils', "GlobalTimeTracker"],
    
    # s3
    [
        "libs.s3",
        (
            "s3_list_files", "s3_upload", "s3_upload_plaintext", "s3_retrieve",
            "s3_retrieve_plaintext"
        )
    ],
    
    # I need to be able to paste code >_O
    ["typing", ("List", "Dict", "Tuple", "Union", 'Counter', 'Deque', 'Dict', 'DefaultDict')]
]
SHELL_PLUS_PRE_IMPORTS = []

# Using the default test runner
TEST_RUNNER = 'django.test.runner.DiscoverRunner'

# server settings....
if DEBUG:
    ALLOWED_HOSTS = "*"
else:
    # we only allow the domain name to be the referrer
    ALLOWED_HOSTS = [DOMAIN_NAME]

PROJECT_ROOT = "."
ROOT_URLCONF = "urls"
STATIC_ROOT = "frontend/static/"
STATIC_URL = "/static/"

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.jinja2.Jinja2',
        'APP_DIRS': False,
        'DIRS': [
            "frontend/templates/",
        ],
        'OPTIONS': {
            'autoescape': True,
            'context_processors': [
                "middleware.context_processors.researcher_context_processor",
                "django.contrib.messages.context_processors.messages",
            ],
        "environment": "config.jinja2.environment",
        },
    },
]


# json serializer crashes with module object does not have attribute .dumps
# or it cannot serialize a datetime object.
SESSION_SERIALIZER = 'django.contrib.sessions.serializers.PickleSerializer'
SESSION_ENGINE = "database.user_models_researcher"

# https-only
# SESSION_COOKIE_SECURE = True

# Changing this causes a runtime warning, but has no effect. Enabling this feature is not equivalent
# to the feature in urls.py.
APPEND_SLASH = False

# We need this to be fairly large, if users ever encounter a problem with this please report it
DATA_UPLOAD_MAX_MEMORY_SIZE = 100 * 1024 * 1024  # 100 MB


# enable Sentry error reporting
if not DEBUG and SENTRY_ELASTIC_BEANSTALK_DSN:
    INSTALLED_APPS.append('raven.contrib.django.raven_compat')
    RAVEN_CONFIG = {'dsn': normalize_sentry_dsn(SENTRY_ELASTIC_BEANSTALK_DSN)}
    
    # sourced directly from https://raven.readthedocs.io/en/stable/integrations/django.html,
    # custom tags have been disabled
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters':
            {
                'verbose':
                    {
                        'format':
                            '%(levelname)s %(asctime)s %(module)s '
                            '%(process)d %(thread)d %(message)s'
                    },
            },
        'handlers':
            {
                'sentry':
                    {
                        'level':
                            'WARNING',  # To capture more than ERROR, change to WARNING, INFO, etc.
                        'class': 'raven.contrib.django.raven_compat.handlers.SentryHandler',
                        # 'tags': {
                        #     'custom-tag': 'x'
                        # },
                    },
                'console':
                    {
                        'level': 'DEBUG',
                        'class': 'logging.StreamHandler',
                        'formatter': 'verbose'
                    }
            },
        'loggers':
            {
                'root': {
                    'level': 'WARNING',
                    'handlers': ['sentry'],
                },
                'django.db.backends':
                    {
                        'level': 'ERROR',
                        'handlers': ['console'],
                        'propagate': True,
                    },
                'raven': {
                    'level': 'WARNING',
                    'handlers': ['console'],
                    'propagate': True,
                },
                'sentry.errors': {
                    'level': 'WARNING',
                    'handlers': ['console'],
                    'propagate': True,
                },
            },
    }

TEST_RUNNER = "redgreenunittest.django.runner.RedGreenDiscoverRunner"
