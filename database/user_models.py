from __future__ import annotations

from typing import Tuple

from Cryptodome.PublicKey import RSA
from django.core.validators import MinLengthValidator
from django.db import models
from django.db.models import F, Func, Manager
from django.db.models.query import QuerySet

from constants.user_constants import ANDROID_API, IOS_API, OS_TYPE_CHOICES, ResearcherRole
from database.common_models import UtilityModel
from database.models import TimestampedModel
from database.study_models import Study
from database.validators import ID_VALIDATOR, STANDARD_BASE_64_VALIDATOR, URL_SAFE_BASE_64_VALIDATOR
from libs.firebase_config import check_firebase_instance
from libs.security import (compare_password, device_hash, generate_easy_alphanumeric_string,
    generate_hash_and_salt, generate_random_string, generate_user_hash_and_salt)


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
    from database.models import (ApiKey, ArchivedEvent, ChunkRegistry, EncryptionErrorMetadata,
        FileToProcess, ForestTask, InterventionDate, IOSDecryptionKey, LineEncryptionError,
        ScheduledEvent, StudyField, SummaryStatisticDaily, UploadTracking)
except ImportError:
    pass


class AbstractPasswordUser(TimestampedModel):
    """ The AbstractPasswordUser (APU) model is used to enable basic password functionality for
    human users of the database, whatever variety of user they may be.

    APU descendants have passwords hashed once with sha256 and many times (as defined in
    settings.py) with PBKDF2, and salted using a cryptographically secure random number generator.
    The sha256 check duplicates the storage of the password on the mobile device, so that the APU's
    password is never stored in a reversible manner. """
    
    password = models.CharField(max_length=44, validators=[URL_SAFE_BASE_64_VALIDATOR],
                                help_text='A hash of the user\'s password')
    salt = models.CharField(max_length=24, validators=[URL_SAFE_BASE_64_VALIDATOR])
    
    # This stub function declaration is present because it is used in the set_password funcion below
    def generate_hash_and_salt(self, password) -> Tuple[bytes, bytes]:
        """ Generate a password hash and random salt from a given password. This is different
        for different types of APUs, depending on whether they use mobile or web. """
        raise NotImplementedError
    
    def set_password(self, password: str):
        """ Sets the instance's password hash to match the hash of the provided string. """
        password_hash, salt = self.generate_hash_and_salt(password.encode())
        # march 2020: this started failing when running postgres in a local environment.  There
        # appears to be some extra type conversion going on, characters are getting expanded when
        # passed in as bytes, causing failures in passing length validation.
        # -- this was caused by the new django behavior that casts bytestrings to their string
        #    representation silently.  Fix is to insert decode statements
        self.password = password_hash.decode()
        self.salt = salt.decode()
        self.save()
    
    def reset_password(self):
        """ Resets the patient's password to match an sha256 hash of a randomly generated string. """
        password = generate_easy_alphanumeric_string()
        self.set_password(password)
        return password
    
    def validate_password(self, compare_me: str) -> bool:
        """ Checks if the input matches the instance's password hash. """
        return compare_password(compare_me.encode(), self.salt.encode(), self.password.encode())
    
    def as_unpacked_native_python(self, remove_timestamps=True) -> dict:
        ret = super().as_unpacked_native_python(remove_timestamps=remove_timestamps)
        ret.pop("password")
        ret.pop("salt")
        ret.pop("access_key_id")
        ret.pop("access_key_secret")
        ret.pop("access_key_secret_salt")
        return ret
    
    class Meta:
        abstract = True


class Participant(AbstractPasswordUser):
    """ The Participant database object contains the password hashes and unique usernames of any
    participants in the study, as well as information about the device the participant is using.
    A Participant uses mobile, so their passwords are hashed accordingly. """
    
    patient_id = models.CharField(
        max_length=8, unique=True, validators=[ID_VALIDATOR],
        help_text='Eight-character unique ID with characters chosen from 1-9 and a-z'
    )
    device_id = models.CharField(
        max_length=256, blank=True,
        help_text='The ID of the device that the participant is using for the study, if any.'
    )
    os_type = models.CharField(
        max_length=16, choices=OS_TYPE_CHOICES, blank=True,
        help_text='The type of device the participant is using, if any.'
    )
    study: Study = models.ForeignKey(
        Study, on_delete=models.PROTECT, related_name='participants', null=False
    )
    
    timezone_name = models.CharField(  # Warning: this is not used yet.
        max_length=256, default="America/New_York", null=False, blank=False
    )
    
    push_notification_unreachable_count = models.SmallIntegerField(default=0, null=False, blank=False)
    
    # new checkin logic
    first_push_notification_checkin = models.DateTimeField(null=True, blank=True)
    last_push_notification_checkin = models.DateTimeField(null=True, blank=True)
    last_survey_checkin = models.DateTimeField(null=True, blank=True)

    # pure tracking
    last_get_latest_surveys = models.DateTimeField(null=True, blank=True)
    last_upload = models.DateTimeField(null=True, blank=True)
    last_register_user = models.DateTimeField(null=True, blank=True)
    last_set_password = models.DateTimeField(null=True, blank=True)
    last_set_fcm_token = models.DateTimeField(null=True, blank=True)
    last_version_code = models.CharField(max_length=32, blank=True, null=True)
    last_version_name = models.CharField(max_length=32, blank=True, null=True)
    last_os_version = models.CharField(max_length=32, blank=True, null=True)

    deleted = models.BooleanField(default=False)
    
    # "Unregistered" means the participant is blocked from uploading further data.
    unregistered = models.BooleanField(default=False)
    easy_enrollment = models.BooleanField(default=False)
    
    
    # related field typings (IDE halp)
    archived_events: Manager[ArchivedEvent]
    chunk_registries: Manager[ChunkRegistry]
    fcm_tokens: Manager[ParticipantFCMHistory]
    field_values: Manager[ParticipantFieldValue]
    files_to_process: Manager[FileToProcess]
    intervention_dates: Manager[InterventionDate]
    scheduled_events: Manager[ScheduledEvent]
    upload_trackers: Manager[UploadTracking]
    # undeclared:
    encryptionerrormetadata_set: Manager[EncryptionErrorMetadata]
    foresttask_set: Manager[ForestTask]
    iosdecryptionkey_set: Manager[IOSDecryptionKey]
    lineencryptionerror_set: Manager[LineEncryptionError]
    pushnotificationdisabledevent_set: Manager[PushNotificationDisabledEvent]
    summarystatisticdaily_set: Manager[SummaryStatisticDaily]
    
    
    @classmethod
    def create_with_password(cls, **kwargs) -> Tuple[str, str]:
        """ Creates a new participant with randomly generated patient_id and password. """
        
        # Ensure that a unique patient_id is generated. If it is not after
        # twenty tries, raise an error.
        patient_id = generate_easy_alphanumeric_string()
        for _ in range(20):
            if not cls.objects.filter(patient_id=patient_id).exists():
                # If patient_id does not exist in the database already
                break
            patient_id = generate_easy_alphanumeric_string()
        else:
            raise RuntimeError('Could not generate unique Patient ID for new Participant.')
        
        # Create a Participant, and generate for them a password
        participant = cls(patient_id=patient_id, **kwargs)
        password = participant.reset_password()  # this saves participant
        return patient_id, password
    
    def generate_hash_and_salt(self, password: bytes) -> Tuple[bytes, bytes]:
        return generate_user_hash_and_salt(password)
    
    def debug_validate_password(self, compare_me: str) -> bool:
        """ Checks if the input matches the instance's password hash, but does the hashing for you
        for use on the command line. This is necessary for manually checking that setting and
        validating passwords work. """
        compare_me = device_hash(compare_me.encode())
        return compare_password(compare_me, self.salt.encode(), self.password.encode())
    
    def assign_fcm_token(self, fcm_instance_id: str):
        ParticipantFCMHistory.objects.create(participant=self, token=fcm_instance_id)
    
    def get_valid_fcm_token(self) -> ParticipantFCMHistory:
        try:
            return self.fcm_tokens.get(unregistered__isnull=True)
        except ParticipantFCMHistory.DoesNotExist:
            return None
    
    def notification_events(self, **archived_event_filter_kwargs) -> Manager[ArchivedEvent]:
        """ convenience methodd for use debugging in the terminal mostly. """
        from database.schedule_models import ArchivedEvent
        return ArchivedEvent.objects.filter(participant=self).filter(
            **archived_event_filter_kwargs
        ).order_by("-scheduled_time")
    
    def get_private_key(self) -> RSA.RsaKey:
        from libs.s3 import get_client_private_key  # weird import triangle
        return get_client_private_key(self.patient_id, self.study.object_id)
    
    @property
    def participant_push_enabled(self) -> bool:
        return (
            self.os_type == ANDROID_API and check_firebase_instance(require_android=True) or
            self.os_type == IOS_API and check_firebase_instance(require_ios=True)
        )
    
    def __str__(self) -> str:
        return f'{self.patient_id} of Study "{self.study.name}"'


class PushNotificationDisabledEvent(UtilityModel):
    # There may be many events
    # this is (currently) purely for record keeping.
    participant: Participant = models.ForeignKey(Participant, null=False, on_delete=models.PROTECT)
    count = models.IntegerField(null=False)
    timestamp = models.DateTimeField(null=False, blank=False, auto_now_add=True, db_index=True)


class ParticipantFCMHistory(TimestampedModel):
    # by making the token unique the solution to problems becomes "reinstall the app"
    participant: Participant = models.ForeignKey("Participant", null=False, on_delete=models.PROTECT, related_name="fcm_tokens")
    token = models.CharField(max_length=256, blank=False, null=False, db_index=True, unique=True,
                             validators=[MinLengthValidator(1)])
    unregistered = models.DateTimeField(null=True, blank=True)


class ParticipantFieldValue(UtilityModel):
    """ These objects can be deleted.  These are values for per-study custom fields for users """
    participant: Participant = models.ForeignKey(Participant, on_delete=models.PROTECT, related_name='field_values')
    field: StudyField = models.ForeignKey('StudyField', on_delete=models.CASCADE, related_name='field_values')
    value = models.TextField(null=False, blank=True, default="")
    
    class Meta:
        unique_together = (("participant", "field"),)


class Researcher(AbstractPasswordUser):
    """ The Researcher database object contains the password hashes and unique usernames of any
    researchers, as well as their data access credentials. A Researcher can be attached to multiple
    Studies, and a Researcher may also be an admin who has extra permissions. A Researcher uses web,
    so their passwords are hashed accordingly. """
    
    username = models.CharField(max_length=32, unique=True, help_text='User-chosen username, stored in plain text')
    site_admin = models.BooleanField(default=False, help_text='Whether the researcher is also an admin')
    
    access_key_id = models.CharField(max_length=64, validators=[STANDARD_BASE_64_VALIDATOR], unique=True, null=True, blank=True)
    access_key_secret = models.CharField(max_length=44, validators=[URL_SAFE_BASE_64_VALIDATOR], blank=True)
    access_key_secret_salt = models.CharField(max_length=24, validators=[URL_SAFE_BASE_64_VALIDATOR], blank=True)
    
    # related field typings (IDE halp)
    api_keys: Manager[ApiKey]
    study_relations: Manager[StudyRelation]
    
    @classmethod
    def create_with_password(cls, username, password, **kwargs) -> Researcher:
        """ Creates a new Researcher with provided username and password. They will initially
        not be associated with any Study. """
        researcher = cls(username=username, **kwargs)
        researcher.set_password(password)
        # todo add check to see if access credentials are in kwargs
        researcher.reset_access_credentials()
        return researcher
    
    @classmethod
    def create_without_password(cls, username) -> Researcher:
        """ Create a new Researcher with provided username and no password """
        r = cls(username=username, password='fakepassword', salt='cab', site_admin=False)
        r.reset_access_credentials()
        return r
    
    @classmethod
    def check_password(cls, username, compare_me) -> bool:
        """ Checks if the provided password matches the hash of the provided Researcher's password. """
        if not Researcher.objects.filter(username=username).exists():
            return False
        researcher = Researcher.objects.get(username=username)
        return researcher.validate_password(compare_me)
    
    @classmethod
    def filter_alphabetical(self, *args, **kwargs) -> QuerySet[Researcher]:
        """ Sort the Researchers a-z by username ignoring case, exclude special user types. """
        return (
            Researcher.objects
                .annotate(username_lower=Func(F('username'), function='LOWER'))
                .order_by('username_lower')
                .filter(*args, **kwargs)
        )
    
    def get_administered_researchers(self) -> QuerySet[Researcher]:
        studies = self.study_relations.filter(
            relationship=ResearcherRole.study_admin).values_list("study_id", flat=True)
        researchers = StudyRelation.objects.filter(
            study_id__in=studies).values_list("researcher_id", flat=True).distinct()
        return Researcher.objects.filter(id__in=researchers)
    
    def get_administered_researchers_by_username(self) -> QuerySet[Researcher]:
        return (
            self.get_administered_researchers()
                .annotate(username_lower=Func(F('username'), function='LOWER'))
                .order_by('username_lower')
        )
    
    def get_administered_studies_by_name(self) -> QuerySet[Study]:
        from database.models import Study
        return Study._get_administered_studies_by_name(self)
    
    def generate_hash_and_salt(self, password: bytes) -> Tuple[bytes, bytes]:
        return generate_hash_and_salt(password)
    
    def elevate_to_site_admin(self):
        self.site_admin = True
        self.save()
    
    def elevate_to_study_admin(self, study):
        study_relation = StudyRelation.objects.get(researcher=self, study=study)
        study_relation.relationship = ResearcherRole.study_admin
        study_relation.save()
    
    def validate_access_credentials(self, proposed_secret_key: str) -> bool:
        """ Returns True/False if the provided secret key is correct for this user. """
        return compare_password(
            proposed_secret_key.encode(),
            self.access_key_secret_salt.encode(),
            self.access_key_secret.encode(),
        )
    
    def reset_access_credentials(self) -> Tuple[str, str]:
        access_key = generate_random_string()[:64]
        secret_key = generate_random_string()[:64]
        secret_hash, secret_salt = generate_hash_and_salt(secret_key)
        self.access_key_id = access_key.decode()
        self.access_key_secret = secret_hash.decode()
        self.access_key_secret_salt = secret_salt.decode()
        self.save()
        return access_key.decode(), secret_key.decode()
    
    def get_admin_study_relations(self) -> QuerySet[StudyRelation]:
        return self.study_relations.filter(relationship=ResearcherRole.study_admin)
    
    def get_researcher_study_relations(self) -> QuerySet[StudyRelation]:
        return self.study_relations.filter(relationship=ResearcherRole.researcher)
    
    def get_researcher_studies_by_name(self) -> QuerySet[Study]:
        return Study.get_researcher_studies_by_name(self)
    
    def get_visible_studies_by_name(self) -> QuerySet[Study]:
        if self.site_admin:
            return Study.get_all_studies_by_name()
        else:
            return self.get_researcher_studies_by_name()
    
    def is_study_admin(self) -> bool:
        return self.get_admin_study_relations().exists()
    
    def is_an_admin(self) -> bool:
        return self.site_admin or self.is_study_admin()
    
    def check_study_admin(self, study_id: int) -> bool:
        return self.study_relations.filter(
            relationship=ResearcherRole.study_admin,
            study_id=study_id,
        ).exists()
    
    def is_site_admin_or_study_admin(self, study_id: int) -> bool:
        return self.site_admin or self.check_study_admin(study_id)
    
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
        return "%s is a %s in %s" % (self.researcher.username,
                                     self.relationship.replace("_", " ").title(),
                                     self.study.name)
