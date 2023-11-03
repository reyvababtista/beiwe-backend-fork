import json

from constants.data_stream_constants import CALL_LOG, GPS, SURVEY_ANSWERS, TEXTS_LOG

from forest.constants import Frequency


ROOT_FOREST_TASK_PATH = "/tmp/forest/"

FOREST_PICKLING_ERROR = "This Forest task's parameters directly referenced code objects in the Forest codebase which have changed such that they cannot be recovered."

FOREST_TASKVIEW_PICKLING_ERROR = "An error occurred when trying to view this tasks parameters.  This is likely due to a change in the Forest codebase."

FOREST_TASKVIEW_PICKLING_EMPTY = "This task's saved parameters are empty... ¯\\_(ツ)_/¯"

class ForestTree:
    """ Todo: Once we upgrade to Django 3, use TextChoices """
    jasmine = "jasmine"
    willow = "willow"
    sycamore = "sycamore"
    
    @classmethod
    def choices(cls):
        return [(choice, choice.title()) for choice in cls.values()]
    
    @classmethod
    def values(cls):
        return [cls.jasmine, cls.willow, cls.sycamore]


class ForestTaskStatus:
    queued = 'queued'
    running = 'running'
    success = 'success'
    error = 'error'
    cancelled = 'cancelled'
    
    @classmethod
    def choices(cls):
        return [(choice, choice.title()) for choice in cls.values()]
    
    @classmethod
    def values(cls):
        return [cls.queued, cls.running, cls.success, cls.error, cls.cancelled]


YEAR_MONTH_DAY = ('year', 'month', 'day')
SYCAMORE_DATE_FORMAT = "%Y-%m-%d"

# the following dictionary is a mapping of output CSV fields from various Forest Trees to their
# summary statistic names.  Note that this data structure is imported and used in tableau constants.

TREE_COLUMN_NAMES_TO_SUMMARY_STATISTICS = {
    # Jasmine, GPS
    "diameter": "jasmine_distance_diameter",
    "max_dist_home": "jasmine_distance_from_home",
    "dist_traveled": "jasmine_distance_traveled",
    "av_flight_length": "jasmine_flight_distance_average",
    "sd_flight_length": "jasmine_flight_distance_stddev",
    "av_flight_duration": "jasmine_flight_duration_average",
    "sd_flight_duration": "jasmine_flight_duration_stddev",
    "missing_time": "jasmine_gps_data_missing_duration",
    "home_time": "jasmine_home_duration",
    "radius": "jasmine_gyration_radius",
    "num_sig_places": "jasmine_significant_location_count",
    "entropy": "jasmine_significant_location_entropy",
    "total_pause_time": "jasmine_pause_time",
    "obs_duration": "jasmine_obs_duration",
    "obs_day": "jasmine_obs_day",
    "obs_night": "jasmine_obs_night",
    "total_flight_time": "jasmine_total_flight_time",
    "av_pause_duration": "jasmine_av_pause_duration",
    "sd_pause_duration": "jasmine_sd_pause_duration",
    
    # Willow, Texts
    "num_r": "willow_incoming_text_count",
    "num_r_tel": "willow_incoming_text_degree",
    "total_char_r": "willow_incoming_text_length",
    "num_s": "willow_outgoing_text_count",
    "num_s_tel": "willow_outgoing_text_degree",
    "total_char_s": "willow_outgoing_text_length",
    "text_reciprocity_incoming": "willow_incoming_text_reciprocity",
    "text_reciprocity_outgoing": "willow_outgoing_text_reciprocity",
    "num_mms_s": "willow_outgoing_MMS_count",
    "num_mms_r": "willow_incoming_MMS_count",
    
    # willow, calls
    "num_in_call": "willow_incoming_call_count",
    "num_in_caller": "willow_incoming_call_degree",
    "total_mins_in_call": "willow_incoming_call_duration",
    "num_out_call": "willow_outgoing_call_count",
    "num_out_caller": "willow_outgoing_call_degree",
    "total_mins_out_call": "willow_outgoing_call_duration",
    "num_mis_call": "willow_missed_call_count",
    "num_mis_caller": "willow_missed_callers",
    
    # sycamore, survey frequency
    "num_surveys": "sycamore_total_surveys",
    "num_complete_surveys": "sycamore_total_completed_surveys",
    "num_opened_surveys": "sycamore_total_opened_surveys",
    "avg_time_to_submit": "sycamore_average_time_to_submit",
    "avg_time_to_open": "sycamore_average_time_to_open",
    "avg_duration": "sycamore_average_duration",
}

NO_DATA_ERROR = 'No chunked data found for participant for the dates specified.'
CLEANUP_ERROR = "\n\nThis task encountered an error cleaning up  after itself.\n\n"

# These Forest Trees are most recently updated from commit fcc49a74057f98b1b26079a0257b3e9d7c27a98f

# default forest parameters for every supported tree.
# Global:
#   study_folder
#   output_folder
#   tz_str  // tz_str is inserted based on the study's timezone.
#   time_start*
#   time_end*
# Time start and end are odd, they take a decomposed list of a datetime object's components, which
# we have converter for in libs.utils.date_utils - datetime_to_list. This is a hangover from when
# we were jsonifying the parameters.
#   Except for Sycamore doesn't. It just takes a YYYY-MM-DD string.
#     And also they are named start_date and end_date.
#   Code for all of this is in forest models.


class DefaultForestParameters:
    jasmine_defaults = {
        "frequency": Frequency.DAILY,
        "save_traj": False,
        ## all_memory_dict and all_bv_set are special pickled parameters that may be large, stored
        #   in s3 and referenced by a s3 key.
        # all_memory_dict: Optional[dict] = None,
        # all_bv_set: Optional[dict] = None,
        ## the rest are optionals:
        # places_of_interest: Optional[list] = None,
        # osm_tags: Optional[List[OSMTags]] = None,
        # participant_ids: Optional[list] = None,
        # parameters: Optional[Hyperparameters] = None,
    }
    willow_defaults = {
        "frequency": Frequency.DAILY,
        ## the rest are optionals
        # beiwe_id: Optional[List[str]] = None,
    }
    sycamore_defaults = {
        "submits_timeframe": Frequency.DAILY,
        ## "config_path" and "interventions_path" are generated at runtime.
        ## "start_date" and "end_date" are YYYY-MM-DD strings.
        # the rest are optionals:
        # interventions_filepath: Optional[str] = None,
        # users: Optional[List] = None,
        # history_path: Optional[str] = None
    }


DEFAULT_FOREST_PARAMETERS_LOOKUP = {
    ForestTree.jasmine: DefaultForestParameters.jasmine_defaults,
    ForestTree.willow: DefaultForestParameters.willow_defaults,
    ForestTree.sycamore: DefaultForestParameters.sycamore_defaults,
}


# special tree parameters
PARAMETER_ALL_BV_SET = "all_bv_set"
PARAMETER_ALL_MEMORY_DICT = "all_memory_dict"
PARAMETER_CONFIG_PATH = "config_path"
PARAMETER_INTERVENTIONS_FILEPATH = "interventions_filepath"

# We exclude some parameters from being pickled and stored in the database
NON_PICKLED_PARAMETERS = [
    # toolarge and not intended to be stored in the database,
    PARAMETER_ALL_BV_SET,
    PARAMETER_ALL_MEMORY_DICT,
    # generated at runtime (temporary folders)
    PARAMETER_CONFIG_PATH,
    PARAMETER_INTERVENTIONS_FILEPATH,
]

class ForestFiles:
    # documented at https://forest.beiwe.org/en/latest/#forest-trees
    jasmine = [GPS]
    willow = [CALL_LOG, TEXTS_LOG]
    sycamore = [SURVEY_ANSWERS]
    
    @classmethod
    def lookup(cls, tree_name: str):
        return getattr(cls, tree_name)
