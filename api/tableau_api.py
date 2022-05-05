import json
from typing import List

from django.db.models import F
from django.http import StreamingHttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from authentication.tableau_authentication import authenticate_tableau
from constants.tableau_api_constants import FIELD_TYPE_MAP, SERIALIZABLE_FIELD_NAMES
from database.tableau_api_models import SummaryStatisticDaily
from forms.django_forms import ApiQueryForm
from libs.internal_types import TableauRequest
from libs.utils.effiicient_paginator import TableauApiPaginator


FINAL_SERIALIZABLE_FIELD_NAMES = (
    f for f in SummaryStatisticDaily._meta.fields if f.name in SERIALIZABLE_FIELD_NAMES
)


@require_GET
@authenticate_tableau
def get_tableau_daily(request: TableauRequest, study_object_id: str = None):
    form = ApiQueryForm(data=request.GET)
    if not form.is_valid():
        return format_errors(form.errors.get_json_data())
    
    # The don't need to specify the study_id and participant_id fields, those are provided.
    query_fields = [f for f in form.cleaned_data["fields"] if f in SERIALIZABLE_FIELD_NAMES]
    paginator = tableau_query_database(
        study_object_id=study_object_id,  # the object id is validated in the login logic
        query_fields=query_fields,
        **form.cleaned_data,  # already cleaned and validated
    )
    return StreamingHttpResponse(
        paginator.stream_orjson_paginate(), content_type="application/json"
    )


@require_GET
def web_data_connector(request: TableauRequest, study_object_id: str):
    """ Build the columns datastructure for tableau to enumerate the format of the API data. """
    # study_id and participant_id are not part of the SummaryStatisticDaily model, so they aren't
    # populated. They are also related fields that both are proxies for a unique identifier field
    # that has a different name, so we do it manually.
    columns = [
        '[\n', "{id: 'study_id', dataType: tableau.dataTypeEnum.string,},\n",
        "{id: 'participant_id', dataType: tableau.dataTypeEnum.string,},\n"
    ]
    
    for field in FINAL_SERIALIZABLE_FIELD_NAMES:
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


def format_errors(errors: dict) -> str:
    """ Flattens a django validation error dictionary into a json string. """
    messages = []
    for field, field_errs in errors.items():
        messages.extend([err["message"] for err in field_errs])
    return json.dumps({"errors": messages})


def tableau_query_database(
    study_object_id, participant_ids=None, limit=None,  # basics
    end_date=None, start_date=None,                     # time
    order_by="date", order_direction="descending",      # sort
    query_fields: List[str] = None,
    **_  # Because Whimsy is important.                 # ignore everything else
) -> TableauApiPaginator:
    """ Args:
        study_object_id (str): study in which to find data
        end_date (optional[date]): last date to include in search
        start_date (optional[date]): first date to include in search
        limit (optional[int]): maximum number of data points to return
        order_by (str): parameter to sort output by. Must be one in the list of fields to return
        order_direction (str): order to sort in, either "ascending" or "descending"
        participant_ids (optional[list[str]]): a list of participants to limit the search to
    Returns EfficientPaginator of the SummaryStatisticsDaily objects specified by the parameters """
    
    if not query_fields:
        raise Exception("invalid usage")
    
    # Set up filter, order_by, and annotation quargs
    filter_kwargs = {}
    filter_kwargs["participant__study__object_id"] = study_object_id
    if participant_ids:
        filter_kwargs["participant__patient_id__in"] = participant_ids
    if end_date:
        filter_kwargs["date__lte"] = end_date
    if start_date:
        filter_kwargs["date__gte"] = start_date
    
    if order_direction == "descending":
        order_by = "-" + order_by
    
    annotate_kwargs = {"study_id": F("participant__study__object_id")}
    if "participant_id" in query_fields:
        annotate_kwargs["patient_id"] = F("participant__patient_id")
    
    # construct query, apply limit if any, pass to paginator with large page size and return.
    query = SummaryStatisticDaily.objects \
        .annotate(**annotate_kwargs).order_by(order_by).filter(**filter_kwargs)
    
    return TableauApiPaginator(query, 10000, values=query_fields, limit=limit)
