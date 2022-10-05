# to generate the below list run this little script.  Don't use * imports.
from collections import defaultdict
from typing import Union

from django.db.models import Model
from django.db.models.base import ModelBase
from django.db.models.fields.reverse_related import ManyToOneRel, OneToOneRel

from database import models as database_models
from database.common_models import TimestampedModel, UtilityModel
from database.survey_models import Survey

"""
This script prints out type annotations that can be pasted in the static scope of a database model
that will assist your IDE autocompletion and type tracking for ForeignKey "related_name" attributes.
The script includes typing information, either as a comment or as the appropriate class in a real
type annotation whenever the class is declared in the same file and available.

Add to top of files, allows use of types declared later in a file scope in earlier type annotations:
from __future__ import annotations
"""


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
            related_names[database_model].append(
                (
                    related_name,
                    field_relationship.related_model.__name__,
                    field_relationship.related_model
                )
            )

print()
print("from __future__ import annotations")
print("from django.db.models import Manager")
print()
for database_model, list_related_model_stuff in related_names.items():
    print()
    print(f"{database_model.__name__}:")
    
    print("    # related field typings (IDE halp)")
    list_related_model_stuff.sort()
    named = [(name, t, rt) for (name, t, rt) in list_related_model_stuff if not name.endswith("_set")]
    unnamed = [(name, t, rt) for (name, t, rt) in list_related_model_stuff if name.endswith("_set")]
    
    related_name: str
    related_type_name: str
    related_model: Model
    
    for related_name, related_type_name, related_model in named:
        # identify classes in same module
        if database_model.__module__ != related_model.__module__:
            # if file_prefix uses lstrip('database.') with that period it... gets weird
            file_prefix = str(related_model.__module__).lstrip('database').lstrip(".")
            output = f"    {related_name}: Manager  # {file_prefix}.{related_model.__name__}"
        else:
            output = f"    {related_name}: Manager[{related_type_name}]"
        print(output)
    
    if unnamed:
        print("    # undeclared:")
        for related_name, related_type_name, related_model in unnamed:
            if database_model.__module__ != related_model.__module__:
                # if file_prefix uses lstrip('database.') with that period it... gets weird
                file_prefix = str(related_model.__module__).lstrip('database').lstrip(".")
                output = f"    {related_name}: Manager  # {file_prefix}.{related_model.__name__}"
            else:
                output = f"    {related_name}: Manager[{related_type_name}]"
            print(output)
