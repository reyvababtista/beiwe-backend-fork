import functools
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from django.contrib import messages
from django.db.models import QuerySet
from django.http import UnreadablePostError
from django.http.request import HttpRequest
from django.shortcuts import HttpResponseRedirect, redirect
from django.utils import timezone
from django.utils.timezone import is_naive

from constants.message_strings import (PASSWORD_EXPIRED, PASSWORD_RESET_FORCED,
    PASSWORD_RESET_SITE_ADMIN, PASSWORD_RESET_TOO_SHORT, PASSWORD_WILL_EXPIRE)
from constants.user_constants import (ALL_RESEARCHER_TYPES, EXPIRY_NAME, ResearcherRole,
    SESSION_NAME, SESSION_UUID)
from database.study_models import Study
from database.user_models_researcher import Researcher, StudyRelation
from libs.http_utils import easy_url
from libs.internal_types import ResearcherRequest
from libs.password_validation import get_min_password_requirement
from libs.security import generate_easy_alphanumeric_string
from middleware.abort_middleware import abort


DEBUG_ADMIN_AUTHENTICATION = False


def log(*args, **kwargs):
    if DEBUG_ADMIN_AUTHENTICATION:
        print(*args, **kwargs)


# Top level authentication wrappers
def authenticate_researcher_login(some_function):
    """ Decorator for functions (pages) that require a login, redirect to login page on failure. """
    @functools.wraps(some_function)
    def authenticate_and_call(*args, **kwargs):
        request: ResearcherRequest = args[0]
        assert isinstance(request, HttpRequest), \
            f"first parameter of {some_function.__name__} must be an HttpRequest, was {type(request)}."
        
        if check_is_logged_in(request):
            populate_session_researcher(request)
            goto_redirect = determine_password_reset_redirect(request)
            return goto_redirect if goto_redirect else some_function(*args, **kwargs)
        else:
            return redirect("/")
    
    return authenticate_and_call


################################################################################
############################ Website Functions #################################
################################################################################


def logout_researcher(request: HttpRequest):
    """ clear session information for a researcher """
    if SESSION_UUID in request.session:
        del request.session[SESSION_UUID]
    if EXPIRY_NAME in request.session:
        del request.session[EXPIRY_NAME]


def log_in_researcher(request: ResearcherRequest, username: str):
    """ populate session for a researcher """
    request.session[SESSION_UUID] = generate_easy_alphanumeric_string()
    request.session[EXPIRY_NAME] = datetime.now() + timedelta(hours=18)
    request.session[SESSION_NAME] = username


def check_is_logged_in(request: ResearcherRequest):
    """ automatically log out the researcher if their session is timed out, extend session if the
    user is already logged in. """
    if EXPIRY_NAME not in request.session:
        # no session expiry present at all, user is not logged in.
        log("no session expiry present")
        return False
    
    if SESSION_UUID not in request.session:
        # no session uuid present at all, user is not logged in.
        log("no session key present")
        return False
    
    if assert_session_unexpired(request):
        # update the session expiry for another 6 hours
        request.session[EXPIRY_NAME] = datetime.now() + timedelta(hours=6)
        return True
    else:
        log("session had expired")
    logout_researcher(request)
    return False


def assert_session_unexpired(request: ResearcherRequest):
    # probably a development environment issue, sometimes the datetime is naive.
    expiry_datetime = request.session[EXPIRY_NAME]
    if is_naive(expiry_datetime):
        return expiry_datetime > datetime.now()
    else:
        return expiry_datetime > timezone.now()


def populate_session_researcher(request: ResearcherRequest):
    # this function defines the ResearcherRequest, which is purely for IDE assistence
    username = request.session.get("researcher_username", None)
    if username is None:
        log("researcher username was not present in session")
        return abort(400)
    try:
        # Cache the Researcher into request.session_researcher.
        request.session_researcher = Researcher.objects.get(username=username)
    except Researcher.DoesNotExist:
        log("could not identify researcher in session")
        return abort(400)


def determine_password_reset_redirect(request: ResearcherRequest) -> Optional[HttpResponseRedirect]:
    """ This function will manage the popup messages for the researcher.  Currently this is limited
    to the password age warning.  This function will be called on every page load and could cause
    duplicates, but I don't have a better solution right now. """
    # case: the password reset page would otherwise be infinitely redirected to itself.
    # need to allow user to log out and set a new password, all other endpoints will result in 302
    if request.get_raw_uri().endswith(("manage_credentials", "reset_admin_password", "logout")):
        return None
    
    researcher = request.session_researcher
    
    # if the researcher has a forced password reset, or the researcher is on a study that requires
    # a minimum password length, force them to the reset password page.
    if researcher.password_force_reset:
        log("password reset forced")
        messages.error(request, PASSWORD_RESET_FORCED)
        return redirect(easy_url("admin_pages.manage_credentials"))
    if researcher.password_min_length < get_min_password_requirement(researcher):
        log("password reset min length")
        messages.error(request, PASSWORD_RESET_SITE_ADMIN if researcher.site_admin else PASSWORD_RESET_TOO_SHORT)
        return redirect(easy_url("admin_pages.manage_credentials"))
    
    # get smallest password max age from studies the researcher is on
    max_age_days = researcher.study_relations \
                       .filter(study__password_max_age_enabled=True) \
                       .order_by("study__password_max_age_days") \
                       .values_list("study__password_max_age_days", flat=True) \
                       .first()
    
    if max_age_days:
        log("any password reset checks")
        # determine the age of the password, if it is within 7 days of expiring warn the user,
        # if it is expired force them to the reset password page.
        password_age_days = (timezone.now() - researcher.password_last_changed).days
        if password_age_days > max_age_days:
            messages.error(request, PASSWORD_EXPIRED)
            log("password expired, redirecting")
            return redirect(easy_url("admin_pages.manage_credentials"))
        elif password_age_days > max_age_days - 7:
            messages.warning(request, PASSWORD_WILL_EXPIRE.format(days=max_age_days - password_age_days))


def assert_admin(request: ResearcherRequest, study_id: int):
    """ This function will throw a 403 forbidden error and stop execution.  Note that the abort
        directly raises the 403 error, if we don't hit that return True. """
    session_researcher = request.session_researcher
    if not session_researcher.site_admin and not session_researcher.check_study_admin(study_id):
        messages.warning("This user does not have admin privilages on this study.")
        log("no admin privilages")
        return abort(403)
    # allow usage in if statements
    return True


def assert_researcher_under_admin(request: ResearcherRequest, researcher: Researcher, study=None):
    """ Asserts that the researcher provided is allowed to be edited by the session user.
        If study is provided then the admin test is strictly for that study, otherwise it checks
        for admin status anywhere. """
    session_researcher = request.session_researcher
    if session_researcher.site_admin:
        log("site admin checking for researcher")
        return
    
    if researcher.site_admin:
        messages.warning(request, "This user is a site administrator, action rejected.")
        log("target researcher is a site admin")
        return abort(403)
    
    kwargs = dict(relationship=ResearcherRole.study_admin)
    if study is not None:
        kwargs['study'] = study
    
    if researcher.study_relations.filter(**kwargs).exists():
        messages.warning(request, "This user is a study administrator, action rejected.")
        log("target researcher is a study administrator")
        return abort(403)
    
    session_studies = set(session_researcher.get_admin_study_relations().values_list("study_id", flat=True))
    researcher_studies = set(researcher.get_researcher_study_relations().values_list("study_id", flat=True))
    
    if not session_studies.intersection(researcher_studies):
        messages.warning(request, "You are not an administrator for that researcher, action rejected.")
        log("session researcher is not an administrator of target researcher")
        return abort(403)


################################################################################
########################## Study Editing Privileges ############################
################################################################################

class ArgumentMissingException(Exception): pass


def authenticate_researcher_study_access(some_function):
    """ This authentication decorator checks whether the user has permission to to access the
    study/survey they are accessing.
    This decorator requires the specific keywords "survey_id" or "study_id" be provided as
    keywords to the function, and will error if one is not.
    The pattern is for a url with <string:survey/study_id> to pass in this value.
    A site admin is always able to access a study or survey. """
    @functools.wraps(some_function)
    def authenticate_and_call(*args, **kwargs):
        # Check for regular login requirement
        request: ResearcherRequest = args[0]
        assert isinstance(request, HttpRequest), \
            f"first parameter of {some_function.__name__} must be an HttpRequest, was {type(request)}."
        
        if not check_is_logged_in(request):
            log("researcher is not logged in")
            return redirect("/")
        
        populate_session_researcher(request)
        
        try:
            # first get from kwargs, then from the POST request, either one is fine
            survey_id = kwargs.get('survey_id', request.POST.get('survey_id', None))
            study_id = kwargs.get('study_id', request.POST.get('study_id', None))
        except UnreadablePostError:
            return abort(500)
        
        # Check proper usage
        if survey_id is None and study_id is None:
            log("no survey or study provided")
            return abort(400)
        
        if survey_id is not None and study_id is None:
            log("survey was provided but no study was provided")
            return abort(400)
        
        # We want the survey_id check to execute first if both args are supplied, surveys are
        # attached to studies but do not supply the study id.
        if survey_id:
            # get studies for a survey, fail with 404 if study does not exist
            studies = Study.objects.filter(surveys=survey_id)
            if not studies.exists():
                log("no such study 1")
                return abort(404)
            
            # Check that researcher is either a researcher on the study or a site admin,
            # and populate study_id variable
            study_id = studies.values_list('pk', flat=True).get()
        
        # assert that such a study exists
        if not Study.objects.filter(pk=study_id, deleted=False).exists():
            log("no such study 2")
            return abort(404)
        
        # always allow site admins, allow all types of study relations
        if not request.session_researcher.site_admin:
            try:
                relation = StudyRelation.objects \
                    .filter(study_id=study_id, researcher=request.session_researcher) \
                    .values_list("relationship", flat=True).get()
            except StudyRelation.DoesNotExist:
                log("no study relationship for researcher")
                return abort(403)
            
            if relation not in ALL_RESEARCHER_TYPES:
                log("invalid study relationship for researcher")
                return abort(403)
        
        return some_function(*args, **kwargs)
    
    return authenticate_and_call


def get_researcher_allowed_studies_as_query_set(request: ResearcherRequest) -> QuerySet[Study]:
    if request.session_researcher.site_admin:
        return Study.get_all_studies_by_name()
    
    return Study.get_all_studies_by_name().filter(
        id__in=request.session_researcher.study_relations.values_list("study", flat=True)
    )


def get_researcher_allowed_studies(request: ResearcherRequest) -> List[Dict]:
    """
    Return a list of studies which the currently logged-in researcher is authorized to view and edit.
    """
    kwargs = {}
    if not request.session_researcher.site_admin:
        kwargs = dict(study_relations__researcher=request.session_researcher)
    
    return [
        study_info_dict for study_info_dict in
        Study.get_all_studies_by_name().filter(**kwargs).values("name", "object_id", "id", "is_test")
    ]


################################################################################
############################# Site Administrator ###############################
################################################################################

def authenticate_admin(some_function):
    """ Authenticate site admin, checks whether a user is a system admin before allowing access to
    pages marked with this decorator.  If a study_id variable is supplied as a keyword argument, the
    decorator will automatically grab the ObjectId in place of the string provided in a route.

    NOTE: if you are using this function along with the authenticate_researcher_study_access
    decorator you must place this decorator below it, otherwise behavior is undefined and probably
    causes a 500 error inside the authenticate_researcher_study_access decorator. """
    @functools.wraps(some_function)
    def authenticate_and_call(*args, **kwargs):
        request: ResearcherRequest = args[0]
        
        # this is debugging code for the django frontend server port
        if not isinstance(request, HttpRequest):
            raise TypeError(f"request was a {type(request)}, expected {HttpRequest}")
        
        # Check for regular login requirement
        if not check_is_logged_in(request):
            return redirect("/")
        
        populate_session_researcher(request)
        session_researcher = request.session_researcher
        # if researcher is not a site admin assert that they are a study admin somewhere, then test
        # the special case of a the study id, if it is present.
        if not session_researcher.site_admin:
            if not session_researcher.study_relations.filter(relationship=ResearcherRole.study_admin).exists():
                log("not study admin anywhere")
                return abort(403)
            
            # fail if there is a study_id and it either does not exist or the researcher is not an
            # admin on that study.
            if 'study_id' in kwargs:
                if not StudyRelation.objects.filter(
                    researcher=session_researcher,
                    study_id=kwargs['study_id'],
                    relationship=ResearcherRole.study_admin,
                ).exists():
                    log("not study admin on study")
                    return abort(403)
        
        # determine whether to redirect to password the password reset page
        goto_redirect = determine_password_reset_redirect(request)
        return goto_redirect if goto_redirect else some_function(*args, **kwargs)
    
    return authenticate_and_call


def forest_enabled(func):
    """ Decorator for validating that Forest is enabled for this study. """
    @functools.wraps(func)
    def wrapped(*args, **kwargs):
        try:
            study = Study.objects.get(id=kwargs.get("study_id", None))
        except Study.DoesNotExist:
            return abort(404)
        
        if not study.forest_enabled:
            return abort(404)
        
        return func(*args, **kwargs)
    
    return wrapped
