""" Original Document sourced from 
https://samuh.medium.com/using-jinja2-with-django-1-8-onwards-9c58fe1204dc """

from django.contrib.staticfiles.storage import staticfiles_storage
from django.urls import reverse
from jinja2 import Environment

from libs.http_utils import (astimezone_with_tz, easy_url, really_nice_time_format_with_tz,
    time_with_tz)


def environment(**options):
    """ This enables us to use Django template tags like
    {% url “index” %} or {% static “path/to/static/file.js” %}
    in our Jinja2 templates.  """
    env = Environment(
        line_comment_prefix="{#",
        comment_start_string="{% comment %}",
        comment_end_string="{% endcomment %}",
        **options
    )
    env.globals.update(
        {
            "static": staticfiles_storage.url,
            "url": reverse,
            "easy_url": easy_url,
            "astimezone_with_tz": astimezone_with_tz,
            "time_with_tz": time_with_tz,
            "really_nice_time_format_with_tz": really_nice_time_format_with_tz
        }
    )
    return env
