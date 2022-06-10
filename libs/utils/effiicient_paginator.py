from typing import List

from django.db.models import QuerySet
from orjson import dumps as orjson_dumps


class EfficientQueryPaginator:
    """ Contains the base logic functions that as-efficiently-as-possible, preferring memory
    efficiency over performance, returns database objects Queries for the PKs and retrieves results
    using them.
    The result is a minimal memory overhead jit'd database query. """
    
    def __init__(
        self,
        filtered_query: QuerySet,
        page_size: int,
        limit: int = 0,
        values: List[str] = None,
        values_list: List[str] = None,
        flat=True,
    ):
        if (not values and not values_list) or (values and values_list):  # Not. Negotiable.
            raise Exception("exactly one of values or values_list must be provided")
        
        self.page_size = page_size
        self.pk_query = filtered_query.values_list("pk", flat=True)
        self.values = values or values_list
        
        # can't filter after a limit (done in pagination), solution is to limit the pk query.
        if limit:
            self.pk_query = self.pk_query[:limit]
        
        # pass values params intelligently
        if values:
            self.value_query = filtered_query.values(*self.values)
        elif values_list:
            self.value_query = filtered_query.values_list(
                *values_list, flat=flat and len(self.values) == 1
            )
            self.values_list = values_list
    
    # def __iter__(self):
    #     """ Grab a page of PKs, the results via iteration. """
    #     pks = []
    #     for count, pk in enumerate(self.pk_query, start=1):
    #         pks.append(pk)
    #         if count % self.page_size == 0:
    #             for result in self.value_query.filter(pk__in=pks):
    #                 yield result
    #             pks = []
    #
    #     # after iteration, any remaining pks
    #     if pks:
    #         for result in self.value_query.filter(pk__in=pks):
    #             yield result
    
    def paginate(self):
        """ Grab a page of PKs, return results in bulk. """
        pks = []
        for count, pk in enumerate(self.pk_query, start=1):
            pks.append(pk)
            if count % self.page_size == 0:
                # using list(query) the iteration occurs inside cpython and is extremely quick.
                yield list(self.value_query.filter(pk__in=pks))
                pks = []
        
        # after iteration, any remaining pks
        if pks:
            yield list(self.value_query.filter(pk__in=pks))
    
    def stream_orjson_paginate(self):
        """ streams a page by page orjson'd bytes of json list elements """
        yield b"["
        for i, page in enumerate(self.paginate()):
            if i != 0:
                yield b","
            yield orjson_dumps(page)[1:-1]  # this is a bytes object, we cut the first and last brackets
        yield b"]"


class TableauApiPaginator(EfficientQueryPaginator):
    """ This class handles a compatibility issue and some weird python behavior. """
    
    def stream_orjson_paginate(self):
        """ we need to rename the patient_id field, because we can't annotate our way out of this
        one due to a Django limitation. """
        
        if "patient_id" in self.values:
            yield b"["
            for i, page in enumerate(self.paginate()):
                if i != 0:
                    yield b","
                for values_dict in page:
                    values_dict["participant_id"] = values_dict.pop("patient_id")
                yield orjson_dumps(page)[1:-1]
            yield b"]"
        else:
            # For some reason we can't call the super implementation, so I have copy-pasted.
            yield b"["
            for i, page in enumerate(self.paginate()):
                if i != 0:
                    yield b","
                yield orjson_dumps(page)[1:-1]
            yield b"]"
