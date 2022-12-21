from __future__ import annotations

from typing import Tuple

from django.contrib.sessions.backends.db import SessionStore as DBStore
from django.contrib.sessions.base_session import AbstractBaseSession
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Func, Manager
from django.db.models.query import QuerySet
from django.utils import timezone

from constants.user_constants import ResearcherRole, SESSION_NAME
from database.models import TimestampedModel
from database.study_models import Study
from database.user_models_common import AbstractPasswordUser
from database.validators import PASSWORD_VALIDATOR, STANDARD_BASE_64_VALIDATOR
from libs.security import (BadDjangoKeyFormatting, compare_password, django_password_components,
    generate_random_bytestring, generate_random_string, to_django_password_components)


# This is an import hack to improve IDE assistance.
try:
    from database.models import ApiKey, DataAccessRecord
except ImportError:
    pass


class Researcher(AbstractPasswordUser):
    """ The Researcher database object contains the password hashes and unique usernames of any
    researchers, as well as their data access credentials. A Researcher can be attached to multiple
    Studies, and a Researcher may also be an admin who has extra permissions. A Researcher uses web,
    so their passwords are hashed accordingly. """
    DESIRED_ITERATIONS = 310000  # 2022 recommendation pbkdf2 iterations for sha256 is 310,000
    DESIRED_ALGORITHM = "sha256"
    
    username = models.CharField(max_length=32, unique=True, help_text='User-chosen username, stored in plain text')
    site_admin = models.BooleanField(default=False, help_text='Whether the researcher is also an admin')
    
    access_key_id = models.CharField(max_length=64, validators=[STANDARD_BASE_64_VALIDATOR], unique=True, null=True, blank=True)
    access_key_secret = models.CharField(max_length=256, validators=[PASSWORD_VALIDATOR], blank=True)
    
    password_last_changed = models.DateTimeField(null=False, blank=False, default=timezone.now)
    password_force_reset = models.BooleanField(default=True)  # new researchers must reset their password
    # in principle it is somewhat unsafe to store this, but the cryptographic search space is only
    # halved, and it needs to be stored Somewhere, either here or in the current session.
    password_min_length = models.SmallIntegerField(default=8, validators=[MinValueValidator(8)])
    
    # related field typings (IDE halp)
    api_keys: Manager[ApiKey]
    study_relations: Manager[StudyRelation]
    data_access_record: Manager[DataAccessRecord]
    web_sessions: Manager[ResearcherSession]
    
    ## User Creation and Passwords
    @classmethod
    def create_with_password(cls, username, password, **kwargs) -> Researcher:
        """ Creates a new Researcher with provided username and password. They will initially
        not be associated with any Study. """
        researcher = cls(username=username, **kwargs)
        researcher.set_password(password)
        # TODO: add check to see if access credentials are in kwargs
        researcher.reset_access_credentials()
        return researcher
    
    def set_password(self, password: str):
        """ Updates the password_last_changed field and then runs normal password setting logic. """
        # okay we can't stick a forced logout here, that is too broad of a use.
        self.password_last_changed = timezone.now()
        self.password_min_length = len(password)
        # set_password calls save(), and we don't want to set values if it (somehow) fails
        super().set_password(password)
    
    @classmethod
    def check_password(cls, username: str, compare_me: str) -> bool:
        """ Checks if the provided password matches the hash of the provided Researcher's password. """
        if not Researcher.objects.filter(username=username).exists():
            return False
        researcher = Researcher.objects.get(username=username)
        return researcher.validate_password(compare_me)
    
    def force_global_logout(self):
        """ Deletes all sessions for this user, forcing a logout and automatic redirection to the
        login page of any and all active website sessions. """
        self.web_sessions.all().delete()
    
    ## User Roles
    def elevate_to_site_admin(self):
        self.site_admin = True
        self.save()
    
    def elevate_to_study_admin(self, study):
        study_relation = StudyRelation.objects.get(researcher=self, study=study)
        study_relation.relationship = ResearcherRole.study_admin
        study_relation.save()
    
    ## Access Credentials
    def validate_access_credentials(self, proposed_secret_key: str) -> bool:
        """ Extract the current credential info, run comparison, will in-place-upgrade the existing
        password hash if there is a match """
        proposed_secret_key = proposed_secret_key.encode()  # needs to be a bytestring twice
        try:
            algorithm, iterations, current_password_hash, salt = django_password_components(self.access_key_secret)
        except BadDjangoKeyFormatting:
            return False
        
        it_matched = compare_password(algorithm, iterations, proposed_secret_key, current_password_hash, salt)
        # whenever we encounter an older password (THAT PASSES OLD-STYLE VALIDATION DUHURR!)
        # use the now-known-correct password value to apply the new-style password.
        if it_matched and (iterations != self.DESIRED_ITERATIONS or algorithm != self.DESIRED_ALGORITHM):
            self.set_access_credentials(self.access_key_id, proposed_secret_key)
        return it_matched
    
    def reset_access_credentials(self) -> Tuple[str, str]:
        """ Replaces access credentials with """
        access_key = generate_random_string(64)
        secret_key = generate_random_bytestring(64)
        self.set_access_credentials(access_key, secret_key)
        return access_key, secret_key.decode()
    
    def set_access_credentials(self, access_key: str, secret_key: bytes) -> Tuple[bytes, bytes]:
        secret_hash, secret_salt = self.generate_hash_and_salt(secret_key)
        self.access_key_id = access_key
        self.access_key_secret = to_django_password_components(
            self.DESIRED_ALGORITHM, self.DESIRED_ITERATIONS, secret_hash, secret_salt
        )
        self.save()
        return secret_hash, secret_salt
    
    ## Logic
    def is_study_admin(self) -> bool:
        return self.get_admin_study_relations().exists()
    
    def is_an_admin(self) -> bool:
        return self.site_admin or self.is_study_admin()
    
    def check_study_admin(self, study_id: int) -> bool:
        return self.study_relations.filter(
            relationship=ResearcherRole.study_admin, study_id=study_id).exists()
    
    def is_site_admin_or_study_admin(self, study_id: int) -> bool:
        return self.site_admin or self.check_study_admin(study_id)
    
    ## Filters
    @classmethod
    def filter_alphabetical(cls, *args, **kwargs) -> QuerySet[Researcher]:
        """ Sort the Researchers a-z by username ignoring case, exclude special user types. """
        return Researcher.objects \
                .annotate(username_lower=Func(F('username'), function='LOWER')) \
                .order_by('username_lower') \
                .filter(*args, **kwargs)
    
    def get_administered_researchers(self) -> QuerySet[Researcher]:
        studies = self.study_relations.filter(
            relationship=ResearcherRole.study_admin).values_list("study_id", flat=True)
        researchers = StudyRelation.objects.filter(
            study_id__in=studies).values_list("researcher_id", flat=True).distinct()
        return Researcher.objects.filter(id__in=researchers)
    
    def get_administered_studies_by_name(self) -> QuerySet[Study]:
        return Study._get_administered_studies_by_name(self)
    
    def get_admin_study_relations(self) -> QuerySet[StudyRelation]:
        return self.study_relations.filter(relationship=ResearcherRole.study_admin)
    
    def get_researcher_study_relations(self) -> QuerySet[StudyRelation]:
        return self.study_relations.filter(relationship=ResearcherRole.researcher)
    
    def get_researcher_studies_by_name(self) -> QuerySet[Study]:
        return Study.get_researcher_studies_by_name(self)
    
    def get_visible_studies_by_name(self) -> QuerySet[Study]:
        # site admins [probably] don't have StudyRelations
        if self.site_admin:
            return Study.get_all_studies_by_name()
        else:
            return self.get_researcher_studies_by_name()
    
    ## Display
    def __str__(self) -> str:
        if self.site_admin:
            return f"{self.username} (Site Admin)"
        return f"{self.username}"


class StudyRelation(TimestampedModel):
    """ This is the through-model for defining the relationship between a researcher and a study. """
    study: Study = models.ForeignKey(
        Study, on_delete=models.CASCADE, related_name='study_relations', null=False, db_index=True
    )
    researcher: Researcher = models.ForeignKey(
        'Researcher', on_delete=models.CASCADE, related_name='study_relations', null=False, db_index=True
    )
    relationship = models.CharField(max_length=32, null=False, blank=False, db_index=True)
    
    class Meta:
        unique_together = ["study", "researcher"]
    
    def __str__(self):
        return "%s is a %s in %s" % (
            self.researcher.username, self.relationship.replace("_", " ").title(), self.study.name
        )


## Custom Session classes for Researchers
# In order to associate sessions with researchers, we need to create a custom session model
# this code is based off the stackoverflow answer found here:
# https://stackoverflow.com/questions/59617751/how-to-make-a-django-user-inactive-and-invalidate-all-their-sessions

class ResearcherSession(AbstractBaseSession):
    # Custom session model which stores user foreignkey to asssociate sessions with particular users.
    researcher: Researcher = models.ForeignKey(
        Researcher, null=True, on_delete=models.CASCADE, related_name="web_sessions"
    )
    
    @classmethod
    def get_session_store_class(cls):
        return SessionStore


# this class literally needs to be named SessionStore
# This class implements a django session backend using the custom session model above
class SessionStore(DBStore):
    
    @classmethod
    def get_model_class(cls):
        return ResearcherSession
    
    def create_model_instance(self, data: dict):
        """ Using the session, grab the researcher and create a (now queryable!) database session """
        quick_session: ResearcherSession = super().create_model_instance(data)
        try:
            # this value is the session key from a cookie.  Get the researcher attached to the session
            user_id = data.get(SESSION_NAME)
            user = Researcher.objects.get(username=user_id)
        except Researcher.DoesNotExist:
            user = None
        
        quick_session.researcher = user
        return quick_session
