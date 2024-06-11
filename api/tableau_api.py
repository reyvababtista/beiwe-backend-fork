from typing import List

from django.db.models.fields import Field
from django.shortcuts import render
from django.views.decorators.http import require_GET

from authentication.tableau_authentication import authenticate_tableau
from constants.tableau_api_constants import FIELD_TYPE_MAP, SERIALIZABLE_FIELD_NAMES
from database.forest_models import SummaryStatisticDaily
from libs.internal_types import TableauRequest
from libs.summary_statistic_api import summary_statistics_request_handler


FINAL_SERIALIZABLE_FIELDS: List[Field] = [
    f for f in SummaryStatisticDaily._meta.fields if f.name in SERIALIZABLE_FIELD_NAMES
]


@require_GET
@authenticate_tableau
def get_tableau_daily(request: TableauRequest, study_object_id: str = None):
    return summary_statistics_request_handler(request, study_object_id)


@require_GET
def web_data_connector(request: TableauRequest, study_object_id: str):
    """ Build the columns datastructure for tableau to enumerate the format of the API data. """
    # study_id and participant_id are not part of the SummaryStatisticDaily model, so they aren't
    # populated. They are also related fields that both are proxies for a unique identifier field
    # that has a different name, so we do it manually.
    columns = [
        '[\n',
        "{id: 'study_id', dataType: tableau.dataTypeEnum.string,},\n",
        "{id: 'participant_id', dataType: tableau.dataTypeEnum.string,},\n"
    ]
    
    for field in FINAL_SERIALIZABLE_FIELDS:
        for (python_type, tableau_type) in FIELD_TYPE_MAP:
            if isinstance(field, python_type):
                columns.append(f"{{id: '{field.name}', dataType: {tableau_type},}},\n")
                # example line: {id: 'participant_id', dataType: tableau.dataTypeEnum.int,},
                break
        else:
            # if the field is not recognized, supply it to tableau as a string type
            columns.append(f"{{id: '{field.name}', dataType: tableau.dataTypeEnum.string,}},\n")
    
    columns = "".join(columns) + '];'
    return render(request, 'wdc.html', context=dict(study_object_id=study_object_id, cols=columns))
