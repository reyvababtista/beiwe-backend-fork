from cronutils.error_handler import ErrorHandler, ErrorSentry, NullErrorHandler
from raven import Client as SentryClient
from raven.exceptions import InvalidDsn
from raven.transport import HTTPTransport

from config.settings import (SENTRY_ANDROID_DSN, SENTRY_DATA_PROCESSING_DSN,
    SENTRY_ELASTIC_BEANSTALK_DSN, SENTRY_JAVASCRIPT_DSN)
from libs.logging import log_error


def get_dsn_from_string(sentry_type):
    """ Returns a DSN, even if it is incorrectly formatted. """
    if sentry_type == 'android':
        return SENTRY_ANDROID_DSN
    elif sentry_type == 'data':
        return SENTRY_DATA_PROCESSING_DSN
    elif sentry_type == 'eb':
        return SENTRY_ELASTIC_BEANSTALK_DSN
    elif sentry_type == 'js':
        return SENTRY_JAVASCRIPT_DSN
    else:
        raise RuntimeError('Invalid sentry type')


def make_sentry_client(sentry_type, tags=None):
    dsn = get_dsn_from_string(sentry_type)
    tags = tags or {}
    return SentryClient(dsn=dsn, tags=tags, transport=HTTPTransport)
    

def make_error_sentry(sentry_type, tags=None, null=False):
    """ Creates an ErrorSentry, defaults to error limit 10.
    If the applicable sentry DSN is missing will return an ErrorSentry,
    but if null truthy a NullErrorHandler will be returned instead. """
    dsn = get_dsn_from_string(sentry_type)
    tags = tags or {}
    try:
        return ErrorSentry(
            dsn,
            sentry_client_kwargs={'tags': tags, 'transport': HTTPTransport},
            sentry_report_limit=10
        )
    except InvalidDsn as e:
        log_error(e)
        if null:
            return NullErrorHandler()
        else:
            return ErrorHandler()
