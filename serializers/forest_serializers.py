import json

from rest_framework import serializers

from constants.common_constants import DEV_TIME_FORMAT
from database.tableau_api_models import ForestTask


def display_true(a_bool: bool):
    if a_bool is True:
        return "Yes"
    elif a_bool is False:
        return "No"
    else:
        return "Unknown"


# FIXME: Get rid of RFS, see forest_pages.task_log for a partial rewrite
class ForestTaskBaseSerializer(serializers.ModelSerializer):
    created_on_display = serializers.SerializerMethodField()
    forest_tree_display = serializers.SerializerMethodField()
    forest_output_exists_display = serializers.SerializerMethodField()
    forest_param_name = serializers.SerializerMethodField()
    forest_param_notes = serializers.SerializerMethodField()
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
            "forest_param_name",
            "forest_param_notes",
            "forest_output_exists",
            "forest_output_exists_display",
            "params_dict",
            "patient_id",
            "process_download_end_time",
            "process_start_time",
            "process_end_time",
            "status",
            "total_file_size",
        ]
    
    
    def get_created_on_display(self, instance):
        return instance.created_on.strftime(DEV_TIME_FORMAT)
    
    def get_forest_tree_display(self, instance):
        return instance.forest_tree.title()
    
    def get_forest_output_exists_display(self, instance):
        if instance.forest_output_exists is True:
            return "Yes"
        elif instance.forest_output_exists is False:
            return "No"
        else:
            return "Unknown"
    
    def get_forest_param_name(self, instance: ForestTask):
        return instance.forest_param.name if instance.forest_param_or_none else None
    
    def get_forest_param_notes(self, instance: ForestTask):
        return instance.forest_param.notes if instance.forest_param_or_none else None
    
    def get_params_dict(self, instance):
        if instance.params_dict_cache:
            return repr(json.loads(instance.params_dict_cache))
        return repr(instance.get_params_dict())
    
    def get_patient_id(self, instance):
        return instance.participant.patient_id


class ForestTaskCsvSerializer(ForestTaskBaseSerializer):
    pass