from typing import List

from django.urls import URLPattern

# used to indicate if a url redirect is safe to redirect to
IGNORE = "IGNORE"
SAFE = "SAFE"

# These are declared here so that they can be imported, they are populated in urls.py.
LOGIN_REDIRECT_IGNORE: List[URLPattern] = []
LOGIN_REDIRECT_SAFE: List[URLPattern] = []
# urlpatterns probably needs to be lowercase for django to find it
urlpatterns: List[URLPattern] = []
