from typing import Any, Dict, List

from database.common_models import UtilityModel


class EfficientPaginator():
    """ Queries for the PKs and retrieves results using them.
    The result is a minimal memory overhead database query.  """
    
    def __init__(self,
        model: UtilityModel,
        page_size: int,
        filter_kwargs: Dict[str, Any] = None,
        order_args: List[str] = None,
        values: List[str] = None,
        values_list: List[str] = None,
        flat=True
    ):
        filter_kwargs = filter_kwargs or {}
        order_args = order_args or []
        
        # setup efficient-as-possibly query for database PKs
        # using iterator allows quick initial query, but paging may be inconsistent in time.
        self.page_size = page_size
        self.pk_query = (
                model.objects
                .filter(**filter_kwargs)
                .order_by(*order_args)
                .values_list("pk", flat=True)
                .iterator()
            )
        
        if values and values_list:
            raise Exception("one of values and values_list")
        
        # pass params intelligently
        if values:
            self.real_query = model.objects.values(*values)
        elif values_list:
            if flat and len(values_list) == 1:
                self.real_query = model.objects.values_list(*values_list, flat=True)
            else:
                self.real_query = model.objects.values_list(*values_list)
        else:
            self.real_query = model.objects.filter()
        
        # may be unnecessary depending on database backend
        if order_args:
            self.real_query = self.real_query.order_by(*order_args)
    
    def __iter__(self):
        """ Grab a page of PKs, the results via iteration. """
        pks = []
        for count, pk in enumerate(self.pk_query, start=1):
            pks.append(pk)
            if count % self.page_size == 0:
                for result in self.real_query.filter(pk__in=pks):
                    yield result
                pks = []
        
        # after iteration, any remaining pks
        if pks:
            for result in self.real_query.filter(pk__in=pks):
                yield result
    
    def paginate(self):
        """ Grab a page of PKs, return results in bulk. """
        pks = []
        for count, pk in enumerate(self.pk_query, start=1):
            pks.append(pk)
            if count % self.page_size == 0:
                # using list(query) the iteration occurs inside cpython and is extremely quick.
                yield list(self.real_query.filter(pk__in=pks))
                pks = []
        
        # after iteration, any remaining pks
        if pks:
            yield list(self.real_query.filter(pk__in=pks))