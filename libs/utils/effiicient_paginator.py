from typing import Any, Dict, List

from orjson import dumps as orjson_dumps

from database.common_models import UtilityModel


class EfficientPaginator():
    """ Queries for the PKs and retrieves results using them.
    The result is a minimal memory overhead database query. """
    
    def __init__(
        self,
        model: UtilityModel,
        page_size: int,
        limit: int = 0,
        filter_kwargs: Dict[str, Any] = None,
        order_args: List[str] = None,
        annotate_kwargs: Dict = None,
        values: List[str] = None,
        values_list: List[str] = None,
        flat=True,
    ):
        if values and values_list:
            raise Exception("only one of values or values_list may be provided")
        
        filter_kwargs = filter_kwargs or {}
        order_args = order_args or []
        annotate_kwargs = annotate_kwargs or {}
        
        # setup efficient-as-possibly query for database PKs, annotate must be applied in order to
        # handle possible using iterator allows quick initial query, which is universally better.
        self.page_size = page_size
        self.pk_query = model.objects.annotate(**annotate_kwargs) \
            .filter(**filter_kwargs).order_by(*order_args).values_list("pk", flat=True)
        
        # apply limit if provided
        if limit:
            self.pk_query = self.pk_query[:limit]
        
        # and make it an iterator to avoid caching (matters for massive queries)
        self.pk_query = self.page_size.iterator()
        
        # annotate before filtering in case of dependencies
        self.unfiltered_query = model.objects
        if annotate_kwargs:
            self.unfiltered_query = self.unfiltered_query.annotate(**annotate_kwargs)
        
        # pass params intelligently
        if values:
            self.unfiltered_query = self.unfiltered_query.values(*values)
        elif values_list:
            self.unfiltered_query = self.unfiltered_query.values_list(
                *values_list, flat=flat and len(values_list) == 1)
        
        if order_args:  # order of pks is not preserved
            self.unfiltered_query = self.unfiltered_query.order_by(*order_args)
    
    def __iter__(self):
        """ Grab a page of PKs, the results via iteration. """
        pks = []
        for count, pk in enumerate(self.pk_query, start=1):
            pks.append(pk)
            if count % self.page_size == 0:
                for result in self.unfiltered_query.filter(pk__in=pks):
                    yield result
                pks = []
        
        # after iteration, any remaining pks
        if pks:
            for result in self.unfiltered_query.filter(pk__in=pks):
                yield result
    
    def paginate(self):
        """ Grab a page of PKs, return results in bulk. """
        pks = []
        for count, pk in enumerate(self.pk_query, start=1):
            pks.append(pk)
            if count % self.page_size == 0:
                # using list(query) the iteration occurs inside cpython and is extremely quick.
                yield list(self.unfiltered_query.filter(pk__in=pks))
                pks = []
        
        # after iteration, any remaining pks
        if pks:
            yield list(self.unfiltered_query.filter(pk__in=pks))
    
    def stream_orjson_paginate(self):
        """ streams a page by page orjson'd bytes of json list elements """
        yield b"["
        for page in self.paginate():
            yield orjson_dumps(page)[1:-1]
        yield b"]"
