from __future__ import annotations

from typing import Tuple

from django.db import models
from django.db.models import F, Func, Manager
from django.db.models.query import QuerySet

from constants.user_constants import ResearcherRole
from database.models import TimestampedModel
from database.study_models import Study
from database.user_models_common import AbstractPasswordUser
from database.validators import PASSWORD_VALIDATOR, STANDARD_BASE_64_VALIDATOR
from libs.security import (BadDjangoKeyFormatting, compare_password, django_password_components,
    generate_random_bytestring, generate_random_string, to_django_password_components)


# This is an import hack to improve IDE assistance.  Most of these imports are cyclical and fail at
# runtime, but they remain present in the _lexical_ scope of the file.  Python's _parser_ recognizes
# the symbol name, which in turn allows us to use them in type annotations.  There are no _runtime_
# errors because type annotations are completely elided from the runtime.  With these annotations
# your IDE is able to provide type inferencing and other typed assistance throughout the codebase.
#
# By attaching some extra type declarations to model classes for django's dynamically generated
# properties (example: "scheduled_events" on the Participant class below) we magically get type
# information almost everywhere.  (These can be generated for you automatically by running `python
# run_script.py generate_relation_hax` and pasting as required.)
#
# If you must to use an unimportable class (like ArchivedEvent in the notification_events()
# convenience method on Participants below) you will need to use a local import.
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
    
    # related field typings (IDE halp)
    api_keys: Manager[ApiKey]
    study_relations: Manager[StudyRelation]
    data_access_record: Manager[DataAccessRecord]
    
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
    
    @classmethod
    def check_password(cls, username: str, compare_me: str) -> bool:
        """ Checks if the provided password matches the hash of the provided Researcher's password. """
        if not Researcher.objects.filter(username=username).exists():
            return False
        researcher = Researcher.objects.get(username=username)
        return researcher.validate_password(compare_me)
    
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
