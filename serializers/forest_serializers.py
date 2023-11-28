import json

from rest_framework import serializers

from constants.common_constants import DEV_TIME_FORMAT
from database.forest_models import ForestTask


def display_true(a_bool: bool):
    if a_bool is True:
        return "Yes"
    elif a_bool is False:
        return "No"
    else:
        return "Unknown"


#! FIXME: Get rid of DRF, see forest_pages.task_log for a partial rewrite
class ForestTaskBaseSerializer(serializers.ModelSerializer):
    created_on_display = serializers.SerializerMethodField()
    forest_tree_display = serializers.SerializerMethodField()
    forest_output_exists_display = serializers.SerializerMethodField()
    params_dict = serializers.SerializerMethodField()
    patient_id = serializers.SerializerMethodField()
    
    class Meta:
        model = ForestTask
        fields = [
            "created_on_display",
            "data_date_end",
            "data_date_start",
            "id",
            "forest_tree_display",
            "forest_output_exists",
            "forest_output_exists_display",
            "patient_id",
            "process_download_end_time",
            "process_start_time",
            "process_end_time",
            "status",
            "total_file_size",
        ]
    
    def get_created_on_display(self, instance: ForestTask):
        return instance.created_on.strftime(DEV_TIME_FORMAT)
    
    def get_forest_tree_display(self, instance: ForestTask):
        return instance.forest_tree.title()
    
    def get_forest_output_exists_display(self, instance: ForestTask):
        return display_true(instance.forest_output_exists)
    
    def get_params_dict(self, instance: ForestTask):
        return repr(instance.get_params_dict())
    
    def get_patient_id(self, instance: ForestTask):
        return instance.participant.patient_id


class ForestTaskCsvSerializer(ForestTaskBaseSerializer):
    pass
