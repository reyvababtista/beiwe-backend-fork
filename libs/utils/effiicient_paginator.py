from typing import Any, Dict, List

from django.db.models import QuerySet
from orjson import dumps as orjson_dumps

from database.common_models import UtilityModel


class DjangoQueryPaginatorBase:
    """ Contains the base logic functions that as-efficiently-as-possible, preferring memory efficiency over performance, returns database objects
    Queries for the PKs and retrieves results using them.
    The result is a minimal memory overhead database query. """
    
    def __iter__(self):
        """ Grab a page of PKs, the results via iteration. """
        self.value_query: QuerySet
        self.pk_query: QuerySet
        pks = []
        for count, pk in enumerate(self.pk_query, start=1):
            pks.append(pk)
            if count % self.page_size == 0:
                for result in self.value_query.filter(pk__in=pks):
                    yield result
                pks = []
        
        # after iteration, any remaining pks
        if pks:
            for result in self.value_query.filter(pk__in=pks):
                yield result
    
    def paginate(self):
        """ Grab a page of PKs, return results in bulk. """
        self.value_query: QuerySet
        self.pk_query: QuerySet
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
        for page in self.paginate():
            yield orjson_dumps(page)[1:-1]
        yield b"]"


# class EfficientPaginator(DjangoQueryPaginatorBase):
#     def __init__(
#         self,
#         model: UtilityModel,
#         page_size: int,
#         limit: int = 0,
#         filter_kwargs: Dict[str, Any] = None,
#         order_args: List[str] = None,
#         annotate_kwargs: Dict = None,
#         values: List[str] = None,
#         values_list: List[str] = None,
#         flat=True,
#     ):
#         if values and values_list:
#             raise Exception("only one of values or values_list may be provided")
        
#         filter_kwargs = filter_kwargs or {}
#         order_args = order_args or []
#         annotate_kwargs = annotate_kwargs or {}
        
#         # setup efficient-as-possibly query for database PKs, annotate must be applied in order to
#         # handle possible using iterator allows quick initial query, which is universally better.
#         self.page_size = page_size
#         self.pk_query = model.objects.annotate(**annotate_kwargs) \
#             .filter(**filter_kwargs).order_by(*order_args).values_list("pk", flat=True)
        
#         # apply limit if provided
#         if limit:
#             self.pk_query = self.pk_query[:limit]
        
#         # and make it an iterator to avoid caching (matters for massive queries)
#         self.pk_query = self.page_size.iterator()
        
#         # annotate before filtering in case of dependencies
#         self.value_query = model.objects
#         if annotate_kwargs:
#             self.value_query = self.value_query.annotate(**annotate_kwargs)
        
#         # pass params intelligently
#         if values:
#             self.value_query = self.value_query.values(*values)
#         elif values_list:
#             self.value_query = self.value_query.values_list(
#                 *values_list, flat=flat and len(values_list) == 1)
        
#         if order_args:  # order of pks is not preserved
#             self.value_query = self.value_query.order_by(*order_args)


class EfficientQueryPaginator(DjangoQueryPaginatorBase):
    """ Takes a query, sets up to paginate/iterate """
    
    def __init__(
        self,
        filtered_query: QuerySet,
        page_size: int,
        values: List[str] = None,
        values_list: List[str] = None,
        flat=True,
    ):
        if not values and not values_list:
            raise Exception("one of values or values_list must be provided")
        
        if values and values_list:
            raise Exception("only one of values or values_list may be provided")
        
        self.page_size = page_size
        self.pk_query = filtered_query.values_list("pk", flat=True)
        
        # pass params intelligently
        if values:
            self.value_query = filtered_query.values(*values)
        elif values_list:
            self.value_query = filtered_query.values_list(
                *values_list, flat=flat and len(values_list) == 1
            )
        elif not values and not values_list:
            self.value_query = filtered_query