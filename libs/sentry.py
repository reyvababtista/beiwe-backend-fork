from cronutils.error_handler import ErrorHandler, ErrorSentry, NullErrorHandler
from raven import Client as SentryClient
from raven.exceptions import InvalidDsn
from raven.transport import HTTPTransport

from config.settings import (SENTRY_DATA_PROCESSING_DSN, SENTRY_ELASTIC_BEANSTALK_DSN,
    SENTRY_JAVASCRIPT_DSN)
from libs.logging import log_error


def normalize_sentry_dsn(dsn: str):
    if not dsn:
        return dsn
    # "https://xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", "sub.domains.sentry.io/yyyyyy"
    prefix, sentry_io = dsn.split("@")
    if sentry_io.count(".") > 1:
        # sub.domains.sentry.io/yyyyyy -> sentry.io/yyyyyy
        sentry_io = ".".join(sentry_io.rsplit(".", 2)[-2:])
    # https://xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx + @ + sentry.io/yyyyyy"
    return prefix + "@" + sentry_io


def get_dsn_from_string(sentry_type: str):
    """ Returns a DSN, even if it is incorrectly formatted. """
    if sentry_type == 'data':
        return normalize_sentry_dsn(SENTRY_DATA_PROCESSING_DSN)
    elif sentry_type == 'eb':
        return normalize_sentry_dsn(SENTRY_ELASTIC_BEANSTALK_DSN)
    elif sentry_type == 'js':
        return normalize_sentry_dsn(SENTRY_JAVASCRIPT_DSN)
    else:
        raise Exception('Invalid sentry type')


def make_sentry_client(sentry_type: str, tags=None):
    dsn = get_dsn_from_string(sentry_type)
    tags = tags or {}
    return SentryClient(dsn=dsn, tags=tags, transport=HTTPTransport)
    

def make_error_sentry(sentry_type:str, tags:dict=None, null:bool=False):
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
