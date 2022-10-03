from typing import List, Union

from django.db.models import Manager, QuerySet
from django.http.request import HttpRequest

from database.dashboard_models import DashboardColorSetting, DashboardGradient, DashboardInflection
from database.data_access_models import ChunkRegistry, FileToProcess, IOSDecryptionKey
from database.profiling_models import EncryptionErrorMetadata, LineEncryptionError, UploadTracking
from database.schedule_models import (AbsoluteSchedule, ArchivedEvent, Intervention,
    InterventionDate, RelativeSchedule, ScheduledEvent, WeeklySchedule)
from database.security_models import ApiKey
from database.study_models import DeviceSettings, Study, StudyField
from database.survey_models import Survey, SurveyArchive, SurveyBase
from database.system_models import FileAsText, GenericEvent
from database.tableau_api_models import ForestParameters, ForestTask, SummaryStatisticDaily
from database.user_models import (AbstractPasswordUser, Participant, ParticipantFCMHistory,
    ParticipantFieldValue, PushNotificationDisabledEvent, Researcher, StudyRelation)


""" This file includes types and typing information that may be missing from your
developmentenvironment or your IDE, as well as some useful type hints. """

#
## Request objects
#

class ResearcherRequest(HttpRequest):
    # these attributes are present on the normal researcher endpoints
    session_researcher: Researcher


class ApiStudyResearcherRequest(HttpRequest):
    api_researcher: Researcher
    api_study: Study


class ApiResearcherRequest(HttpRequest):
    api_researcher: Researcher


class ParticipantRequest(HttpRequest):
    session_participant: Participant


class TableauRequest(HttpRequest): pass

#
## Other classes
#

StrOrBytes = Union[str, bytes]
StrOrParticipantOrStudy = Union[str, Participant, Study]


# Generated with scripts/generate_typing_hax.py on 2022-09-30
AbsoluteScheduleQuerySet = QuerySet[AbsoluteSchedule]
AbstractPasswordUserQuerySet = QuerySet[AbstractPasswordUser]
ApiKeyQuerySet = QuerySet[ApiKey]
ArchivedEventQuerySet = QuerySet[ArchivedEvent]
ChunkRegistryQuerySet = QuerySet[ChunkRegistry]
DashboardColorSettingQuerySet = QuerySet[DashboardColorSetting]
DashboardGradientQuerySet = QuerySet[DashboardGradient]
DashboardInflectionQuerySet = QuerySet[DashboardInflection]
DeviceSettingsQuerySet = QuerySet[DeviceSettings]
EncryptionErrorMetadataQuerySet = QuerySet[EncryptionErrorMetadata]
FileAsTextQuerySet = QuerySet[FileAsText]
FileToProcessQuerySet = QuerySet[FileToProcess]
ForestParametersQuerySet = QuerySet[ForestParameters]
ForestTaskQuerySet = QuerySet[ForestTask]
GenericEventQuerySet = QuerySet[GenericEvent]
IOSDecryptionKeyQuerySet = QuerySet[IOSDecryptionKey]
InterventionDateQuerySet = QuerySet[InterventionDate]
InterventionQuerySet = QuerySet[Intervention]
LineEncryptionErrorQuerySet = QuerySet[LineEncryptionError]
ParticipantFCMHistoryQuerySet = QuerySet[ParticipantFCMHistory]
ParticipantFieldValueQuerySet = QuerySet[ParticipantFieldValue]
ParticipantQuerySet = QuerySet[Participant]
PushNotificationDisabledEventQuerySet = QuerySet[PushNotificationDisabledEvent]
RelativeScheduleQuerySet = QuerySet[RelativeSchedule]
ResearcherQuerySet = QuerySet[Researcher]
ScheduledEventQuerySet = QuerySet[ScheduledEvent]
StudyFieldQuerySet = QuerySet[StudyField]
StudyQuerySet = QuerySet[Study]
StudyRelationQuerySet = QuerySet[StudyRelation]
SummaryStatisticDailyQuerySet = QuerySet[SummaryStatisticDaily]
SurveyArchiveQuerySet = QuerySet[SurveyArchive]
SurveyBaseQuerySet = QuerySet[SurveyBase]
SurveyQuerySet = QuerySet[Survey]
UploadTrackingQuerySet = QuerySet[UploadTracking]
WeeklyScheduleQuerySet = QuerySet[WeeklySchedule]

AbsoluteScheduleManager = Manager[AbsoluteSchedule]
ApiKeyManager = Manager[ApiKey]
ArchivedEventManager = Manager[ArchivedEvent]
ChunkRegistryManager = Manager[ChunkRegistry]
DashboardColorSettingManager = Manager[DashboardColorSetting]
DashboardGradientManager = Manager[DashboardGradient]
DashboardInflectionManager = Manager[DashboardInflection]
DeviceSettingsManager = Manager[DeviceSettings]
FileToProcessManager = Manager[FileToProcess]
InterventionDateManager = Manager[InterventionDate]
InterventionManager = Manager[Intervention]
ParticipantFCMHistoryManager = Manager[ParticipantFCMHistory]
ParticipantFieldValueManager = Manager[ParticipantFieldValue]
ParticipantManager = Manager[Participant]
RelativeScheduleManager = Manager[RelativeSchedule]
ScheduledEventManager = Manager[ScheduledEvent]
StudyFieldManager = Manager[StudyField]
StudyRelationManager = Manager[StudyRelation]
SummaryStatisticDailyManager = Manager[SummaryStatisticDaily]
SurveyArchiveManager = Manager[SurveyArchive]
SurveyManager = Manager[Survey]
UploadTrackingManager = Manager[UploadTracking]
WeeklyScheduleManager = Manager[WeeklySchedule]
