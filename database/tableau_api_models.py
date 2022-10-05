from __future__ import annotations

import json
import pickle
import uuid
from datetime import timedelta
from os.path import join as path_join
from typing import Optional

from django.db import models
from django.db.models import Manager

from constants.forest_constants import (DEFAULT_FOREST_PARAMETERS_LOOKUP, ForestTaskStatus,
    ForestTree, ROOT_FOREST_TASK_PATH, SYCAMORE_DATE_FORMAT)
from database.common_models import TimestampedModel
from database.user_models import Participant
from libs.utils.date_utils import datetime_to_list


#
## GO READ THE MULTILINE STATEMENT AT THE TOP OF services/celery_forest.py
#
class ForestParameters(TimestampedModel):
    """ Model for storing parameter sets used in Forest analyses. """
    name = models.TextField(blank=True, null=False)
    notes = models.TextField(blank=True, null=False)
    tree_name = models.TextField(blank=False, null=False, choices=ForestTree.choices())
    json_parameters = models.TextField(blank=False, null=False)
    deleted = models.BooleanField(default=False)
    
    # related field typings (IDE halp)
    # undeclared:
    foresttask_set: Manager[ForestTask]


class ForestTask(TimestampedModel):
    participant: Participant = models.ForeignKey('Participant', on_delete=models.PROTECT, db_index=True)
    # the external id is used for endpoints that refer to forest trackers to avoid exposing the
    # primary keys of the model. it is intentionally not the primary key
    external_id = models.UUIDField(default=uuid.uuid4, editable=False)
    
    # forest param can be null, means it used defaults
    # access using forest_param_or_none!
    forest_param: ForestParameters = models.ForeignKey(ForestParameters, null=True, blank=True, on_delete=models.PROTECT)  # blank must be true
    params_dict_cache = models.TextField(blank=True)  # Cache of the params used
    
    forest_tree = models.TextField(choices=ForestTree.choices())
    data_date_start = models.DateField()  # inclusive
    data_date_end = models.DateField()  # inclusive
    
    total_file_size = models.BigIntegerField(blank=True, null=True)  # input file size sum for accounting
    process_start_time = models.DateTimeField(null=True, blank=True)
    process_download_end_time = models.DateTimeField(null=True, blank=True)
    process_end_time = models.DateTimeField(null=True, blank=True)
    
    # Whether or not there was any data output by Forest (None indicates unknown)
    forest_output_exists = models.BooleanField(null=True, blank=True)
    
    status = models.TextField(choices=ForestTaskStatus.choices())
    stacktrace = models.TextField(null=True, blank=True, default=None)  # for logs
    forest_version = models.CharField(blank=True, max_length=10)
    
    all_bv_set_s3_key = models.TextField(blank=True)
    all_memory_dict_s3_key = models.TextField(blank=True)
    
    # related field typings (IDE halp)
    jasmine_summary_statistics: Manager[SummaryStatisticDaily]
    sycamore_summary_statistics: Manager[SummaryStatisticDaily]
    willow_summary_statistics: Manager[SummaryStatisticDaily]
    
    #
    ## non-fields
    #
    
    def get_legible_identifier(self) -> str:
        """ Return a human-readable identifier. """
        return "_".join([
            "data",
            self.participant.patient_id,
            self.forest_tree,
            str(self.data_date_start),
            str(self.data_date_end),
        ])
    
    @property
    def taskname(self):
        return self.forest_tree + "_task"
    
    @property
    def forest_param_or_none(self) -> Optional[ForestParameters]:
        # because this is annoying!
        try:
            return self.forest_param
        except ForestParameters.DoesNotExist:
            return None
    
    #
    ## forest tree parameters
    #
    def get_params_dict(self) -> dict:
        """ Return a dict of params to pass into the Forest function. The task flag is used to
        indicate whether this is being called for use in the serializer or for use in a task (in
        which case we can call additional functions as needed). """
        params = {
            "output_folder": self.data_output_path,
            "study_folder": self.data_input_path,
        }
        
        # no forest params implies that we are using the defaults, this may change in the future.
        if self.forest_param_or_none is None:
            params.update(**json.loads(DEFAULT_FOREST_PARAMETERS_LOOKUP[self.forest_tree]))
        else:
            params.update(**json.loads(self.forest_param.json_parameters))
        
        self.handle_tree_specific_date_params(params)
        
        if self.forest_tree == ForestTree.jasmine:
            self.assemble_jasmine_dynamic_params(params)
        if self.forest_tree == ForestTree.sycamore:
            self.assemble_sycamore_folder_path_params(params)
        
        return params
    
    def handle_tree_specific_date_params(self, params: dict):
        if self.forest_tree != ForestTree.sycamore:
            # most trees expect lists of datetime parameters. We need to add a day since this model
            # tracks time end inclusively, but Forest expects it exclusively
            params.update({
                "time_start": datetime_to_list(self.data_date_start),
                "time_end": datetime_to_list(self.data_date_end + timedelta(days=1)),
            })
        else:
            # sycamore expects "time_end" and "time_start" as strings in the format "YYYY-MM-DD"
            params.update({
                "start_date": self.data_date_start.strftime(SYCAMORE_DATE_FORMAT),
                "end_date": (self.data_date_end + timedelta(days=1)).strftime(SYCAMORE_DATE_FORMAT),
            })
    
    def assemble_jasmine_dynamic_params(self, params: dict):
        params["all_bv_set"] = self.get_jasmine_all_bv_set_dict()
        params["all_memory_dict"] = self.get_jasmine_all_memory_dict_dict()
    
    def assemble_sycamore_folder_path_params(self, params: dict):
        params['config_path'] = self.study_config_path
        params['interventions_filepath'] = self.interventions_filepath
    
    # Cached data sets (consider moving out of this file)
    def get_jasmine_all_bv_set_dict(self) -> dict:
        """ Return the unpickled all_bv_set dict. """
        if not self.all_bv_set_s3_key:
            return None  # Forest expects None if it doesn't exist
        from libs.s3 import s3_retrieve
        return pickle.loads(
            s3_retrieve(self.all_bv_set_s3_key, self.participant.study.object_id, raw_path=True)
        )
    
    def get_jasmine_all_memory_dict_dict(self) -> dict:
        """ Return the unpickled all_memory_dict dict. """
        if not self.all_memory_dict_s3_key:
            return None  # Forest expects None if it doesn't exist
        from libs.s3 import s3_retrieve
        return pickle.loads(
            s3_retrieve(self.all_memory_dict_s3_key, self.participant.study.object_id, raw_path=True)
        )
    
    def save_all_bv_set_bytes(self, all_bv_set_bytes):
        from libs.s3 import s3_upload
        self.all_bv_set_s3_key = self.all_bv_set_s3_key_path
        s3_upload(self.all_bv_set_s3_key, all_bv_set_bytes, self.participant, raw_path=True)
        self.save(update_fields=["all_bv_set_s3_key"])
    
    def save_all_memory_dict_bytes(self, all_memory_dict_bytes):
        from libs.s3 import s3_upload
        self.all_memory_dict_s3_key = self.all_memory_dict_s3_key_path
        s3_upload(self.all_memory_dict_s3_key, all_memory_dict_bytes, self.participant, raw_path=True)
        self.save(update_fields=["all_memory_dict_s3_key"])
    
    #
    ## File paths
    #
    @property
    def root_path_for_task(self):
        """ The uuid-folder name for this task """
        return path_join(ROOT_FOREST_TASK_PATH, str(self.external_id))
    
    @property
    def data_base_path(self):
        """ Path to the base data for this task's tree. """
        return path_join(self.root_path_for_task, self.forest_tree)
    
    @property
    def interventions_filepath(self) -> str:
        """ The study interventions file path for the participant's survey data. """
        filename = self.participant.study.name.replace(' ', '_') + "_interventions.json"
        return path_join(self.data_base_path, filename)
    
    @property
    def study_config_path(self) -> str:
        """ The study configuration file file path. """
        filename = self.participant.patient_id.replace(' ', '_') + "_surveys_and_settings.json"
        return path_join(self.data_base_path, filename)
    
    @property
    def data_input_path(self) -> str:
        """ Path to the input data folder. """
        return path_join(self.data_base_path, "data")
    
    @property
    def data_output_path(self) -> str:
        """ Path to the output data folder. """
        return path_join(self.data_base_path, "output")
    
    @property
    def forest_results_path(self) -> str:
        """ Path to the file that contains the output of Forest. """
        return path_join(self.data_output_path, f"{self.participant.patient_id}.csv")
    
    @property
    def all_bv_set_path(self) -> str:
        """ Jasmine's all_bv_set file for this task. """
        return path_join(self.data_output_path, "all_BV_set.pkl")
    
    @property
    def all_memory_dict_path(self) -> str:
        """ Jasmine's all_memory_dict file for this task. """
        return path_join(self.data_output_path, "all_memory_dict.pkl")
    
    #
    ## AWS S3 key paths
    #
    @property
    def s3_base_folder(self) -> str:
        """ Base file path on AWS S3 for any forest data on this study """
        return path_join(self.participant.study.object_id, "forest")
    
    @property
    def all_bv_set_s3_key_path(self):
        """ Jasmine's all_bv_set file for this study on AWS S3. """
        return path_join(self.s3_base_folder, 'all_bv_set.pkl')
    
    @property
    def all_memory_dict_s3_key_path(self):
        """ Jasmine's all_memory_dict file for this study on AWS S3. """
        return path_join(self.s3_base_folder, 'all_memory_dict.pkl')


class SummaryStatisticDaily(TimestampedModel):
    participant: Participant = models.ForeignKey(Participant, on_delete=models.CASCADE)
    date = models.DateField(db_index=True)
    timezone = models.CharField(max_length=10, null=False, blank=False) # abbreviated time zone names are max 4 chars.
    
    # Beiwe data quantities
    beiwe_accelerometer_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_ambient_audio_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_app_log_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_bluetooth_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_calls_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_devicemotion_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_gps_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_gyro_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_identifiers_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_image_survey_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_ios_log_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_magnetometer_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_power_state_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_proximity_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_reachability_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_survey_answers_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_survey_timings_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_texts_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_audio_recordings_bytes = models.PositiveIntegerField(null=True, blank=True)
    beiwe_wifi_bytes = models.PositiveIntegerField(null=True, blank=True)
    
    # GPS
    jasmine_distance_diameter = models.FloatField(null=True, blank=True)
    jasmine_distance_from_home = models.FloatField(null=True, blank=True)
    jasmine_distance_traveled = models.FloatField(null=True, blank=True)
    jasmine_flight_distance_average = models.FloatField(null=True, blank=True)
    jasmine_flight_distance_stddev = models.FloatField(null=True, blank=True)
    jasmine_flight_duration_average = models.FloatField(null=True, blank=True)
    jasmine_flight_duration_stddev = models.FloatField(null=True, blank=True)
    jasmine_gps_data_missing_duration = models.IntegerField(null=True, blank=True)
    jasmine_home_duration = models.FloatField(null=True, blank=True)
    jasmine_gyration_radius = models.FloatField(null=True, blank=True)
    jasmine_significant_location_count = models.IntegerField(null=True, blank=True)
    jasmine_significant_location_entropy = models.FloatField(null=True, blank=True)
    jasmine_pause_time = models.TextField(null=True, blank=True)
    jasmine_obs_duration = models.FloatField(null=True, blank=True)
    jasmine_obs_day = models.FloatField(null=True, blank=True)
    jasmine_obs_night = models.FloatField(null=True, blank=True)
    jasmine_total_flight_time = models.FloatField(null=True, blank=True)
    jasmine_av_pause_duration = models.FloatField(null=True, blank=True)
    jasmine_sd_pause_duration = models.FloatField(null=True, blank=True)
    
    # Willow, Texts
    willow_incoming_text_count = models.IntegerField(null=True, blank=True)
    willow_incoming_text_degree = models.IntegerField(null=True, blank=True)
    willow_incoming_text_length = models.IntegerField(null=True, blank=True)
    willow_outgoing_text_count = models.IntegerField(null=True, blank=True)
    willow_outgoing_text_degree = models.IntegerField(null=True, blank=True)
    willow_outgoing_text_length = models.IntegerField(null=True, blank=True)
    willow_incoming_text_reciprocity = models.IntegerField(null=True, blank=True)
    willow_outgoing_text_reciprocity = models.IntegerField(null=True, blank=True)
    willow_outgoing_MMS_count = models.IntegerField(null=True, blank=True)
    willow_incoming_MMS_count = models.IntegerField(null=True, blank=True)
    
    # Willow, Calls
    willow_incoming_call_count = models.IntegerField(null=True, blank=True)
    willow_incoming_call_degree = models.IntegerField(null=True, blank=True)
    willow_incoming_call_duration = models.FloatField(null=True, blank=True)
    willow_outgoing_call_count = models.IntegerField(null=True, blank=True)
    willow_outgoing_call_degree = models.IntegerField(null=True, blank=True)
    willow_outgoing_call_duration = models.FloatField(null=True, blank=True)
    willow_missed_call_count = models.IntegerField(null=True, blank=True)
    willow_missed_callers = models.IntegerField(null=True, blank=True)
    
    # Sycamore, Survey Frequency
    sycamore_total_surveys = models.IntegerField(null=True, blank=True)
    sycamore_total_completed_surveys = models.IntegerField(null=True, blank=True)
    sycamore_total_opened_surveys = models.IntegerField(null=True, blank=True)
    sycamore_average_time_to_submit = models.FloatField(null=True, blank=True)
    sycamore_average_time_to_open = models.FloatField(null=True, blank=True)
    sycamore_average_duration = models.FloatField(null=True, blank=True)
    
    jasmine_task: ForestTask = models.ForeignKey(ForestTask, blank=True, null=True, on_delete=models.PROTECT, related_name="jasmine_summary_statistics")
    willow_task: ForestTask = models.ForeignKey(ForestTask, blank=True, null=True, on_delete=models.PROTECT, related_name="willow_summary_statistics")
    sycamore_task: ForestTask = models.ForeignKey(ForestTask, blank=True, null=True, on_delete=models.PROTECT, related_name="sycamore_summary_statistics")
    
    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['date', 'participant'], name="unique_summary_statistic")
        ]
