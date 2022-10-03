# to generate the below list run this little script.  Don't use * imports.
from collections import defaultdict
from typing import Union
from django.db.models import Manager, QuerySet
from django.db.models.base import ModelBase
from database import models as database_models
from database.common_models import TimestampedModel, UtilityModel
from pprint import pprint
from django.db.models.fields.reverse_related import OneToOneRel, ManyToOneRel

from database.survey_models import Survey
from datetime import date

related_names = defaultdict(list)

for _, database_model in vars(database_models).items():
    if (
        isinstance(database_model, ModelBase) and UtilityModel in database_model.mro() and
        database_model is not UtilityModel and database_model is not TimestampedModel
    ):
        # (just adding some ~fake types here for syntax)
        database_model: Survey
        field_relationship: Union[OneToOneRel, ManyToOneRel]
        code_additions = []
        for field_relationship in database_model._meta.related_objects:
            # we only want the named relations
            if field_relationship.related_name is None:
                # print("none case for", field_relationship)
                # pprint(pprint(vars(field_relationship)))
                related_name = field_relationship.related_model.__name__.lower() + "_set"
            else:
                related_name = field_relationship.related_name
            related_names[database_model.__name__].append((related_name, field_relationship.related_model.__name__))

print()
print("from django.db.models import QuerySet")
print()
for database_model_name, list_related_names in related_names.items():
    print()
    print(f"{database_model_name}:")
    print("    # related field typings (enhances ide assistance)")
    list_related_names.sort()
    named = [(name, t) for (name, t) in list_related_names if not name.endswith("_set")]
    unnamed = [(name, t) for (name, t) in list_related_names if name.endswith("_set")]
    
    for related_name, related_type in named:
        # print(f"    {related_name}: QuerySet[{related_type}]")
        print(f"    {related_name}: Union[Manager, List[{related_type}]]")
    
    if unnamed:
        print("    # undeclared:")
        for related_name, related_type in unnamed:
            # print(f"    {related_name}: QuerySet[{related_type}]")
            print(f"    {related_name}: Union[Manager, List[{related_type}]]")
