from django.db import models
from database.common_models import TimestampedModel
from database.study_models import Study
from database.user_models import Participant


class SummaryStatisticDaily(TimestampedModel):
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE)
    study = models.ForeignKey(Study, on_delete=models.CASCADE)
    date = models.DateField(db_index=True)
    distance_diameter = models.IntegerField()
    distance_from_home = models.IntegerField()
    distance_traveled = models.IntegerField()
    flight_distance_average = models.IntegerField()
    flight_distance_standard_deviation = models.IntegerField()
    flight_duration_average = models.IntegerField()
    flight_duration_standard_deviation = models.IntegerField()
    gps_data_missing_duration = models.IntegerField()
    home_duration = models.IntegerField()
    physical_circadian_rhythm = models.FloatField()
    physical_circadian_rhythm_stratified = models.FloatField()
    radius_of_gyration = models.IntegerField()
    significant_location_count = models.IntegerField()
    significant_location_entropy = models.IntegerField()
    stationary_fraction = models.TextField()
    text_incoming_count = models.IntegerField()
    text_incoming_degree = models.IntegerField()
    text_incoming_length = models.IntegerField()
    text_incoming_responsiveness = models.IntegerField()
    text_outgoing_count = models.IntegerField()
    text_outgoing_degree = models.IntegerField()
    text_outgoing_length = models.IntegerField()
    text_reciprocity = models.IntegerField()
    call_incoming_count = models.IntegerField()
    call_incoming_degree = models.IntegerField()
    call_incoming_duration = models.IntegerField()
    call_incoming_responsiveness = models.IntegerField()
    call_outgoing_count = models.IntegerField()
    call_outgoing_degree = models.IntegerField()
    call_outgoing_duration = models.IntegerField()
    acceleration_direction = models.TextField()
    accelerometer_coverage_fraction = models.TextField()
    accelerometer_signal_variability = models.TextField()
    accelerometer_univariate_summaries = models.FloatField()
    device_proximity = models.BooleanField()
    total_power_events = models.IntegerField()
    total_screen_events = models.IntegerField()
    total_unlock_events = models.IntegerField()
    awake_onset_time = models.DateTimeField()
    sleep_duration = models.IntegerField()
    sleep_onset_time = models.DateTimeField()

class ForestTracker(TimestampedModel):
    participant = models.ForeignKey(
        'Participant', on_delete=models.PROTECT, db_index=True
    )
    forest_tree = models.CharField(max_length=10)
    date_start = models.DateField()  # inclusive
    date_end = models.DateField()  # inclusive

    file_size = models.IntegerField()  # what file? output?
    start_time = models.DateTimeField(null=True)
    end_time = models.DateTimeField(null=True)
    # celery_task_id?
    # time limit?

    QUEUED_STATUS = 1
    RUNNING_STATUS = 2
    SUCCESS_STATUS = 3
    ERROR_STATUS = 4
    STATUS_CHOICES = (
        (QUEUED_STATUS, 'queued'),
        (RUNNING_STATUS, 'running'),
        (SUCCESS_STATUS, 'success'),
        (ERROR_STATUS, 'error'),
    )
    status = models.IntegerField(choices=STATUS_CHOICES)
    stacktrace = models.TextField(null=True, blank=True, default=None)  # for logs
    forest_version = models.CharField(max_length=10)
    commit_hash = models.CharField(max_length=40)
    metadata = models.TextField()  # json string, add validator?
    metadata_hash = models.CharField(max_length=64)


# class ForestTree(TimestampedModel):
#     name = models.CharField(max_length=30)
#
