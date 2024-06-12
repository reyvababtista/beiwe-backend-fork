import csv
from typing import Any, Generator, List, Tuple

from django.db.models import QuerySet
from orjson import dumps as orjson_dumps

from libs.streaming_io import StreamingStringsIO


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
        self.values = values or values_list  # values is a list of field names - rename?
        
        self.doing_values_list = bool(values_list)
        
        # can't filter after a limit (done in pagination), solution is to limit the pk query.
        if limit:
            self.pk_query = self.pk_query[:limit]
        
        # pass values params intelligently
        if values:
            self.value_query = filtered_query.values(*self.values)
        elif values_list:
            self.value_query = filtered_query.values_list(
                *values_list, flat=flat and len(self.values) == 1  # intelligently handle flat=True
            )
            self.values_list = values_list
    
    def __iter__(self) -> Generator[Any, None, None]:
        """ Grab a page of PKs, the results via iteration. (_Might_ have better memory usage.) """
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
    
    def paginate(self) -> Generator[List, None, None]:
        """ Grab a page of PKs, return results in bulk. (Use this one 99% of the time) """
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
    
    def stream_csv(self, header_names: List[str] = None) -> Generator[str, None, None]:
        """ Streams out a page by page csv file for passing into a FileResponse. """
        if not self.doing_values_list:
            raise Exception("stream_csv requires use of values_list parameter.")
        
        # StreamingStringsIO is might be less efficient than perfect StreamingBytesIO streaming,
        # but it handles some type conversion cases
        si = StreamingStringsIO()  # use our special streaming class to make this work
        filewriter = csv.writer(si)
        filewriter.writerow(self.values_list if header_names is None else header_names)
        
        # use the bulk writerows function, should be faster.
        rows: List[Tuple] = []
        for rows in self.paginate():
            filewriter.writerows(rows)
            yield si.getvalue()
            si.empty()
    
    def stream_orjson_paginate(self, **kwargs) -> Generator[bytes, None, None]:
        """ streams a page by page orjson'd bytes of json list elements. Accepts kwargs for orjson. """
        yield b"["
        for i, page in enumerate(self.paginate()):
            if i != 0:
                yield b","
            yield orjson_dumps(page, **kwargs)[1:-1]  # this is a bytes object, we cut the first and last brackets
        yield b"]"
