""" Original Document sourced from 
https://samuh.medium.com/using-jinja2-with-django-1-8-onwards-9c58fe1204dc """

import re
from datetime import date

from django.contrib.staticfiles.storage import staticfiles_storage
from django.urls import reverse
from jinja2 import Environment

from config.settings import SENTRY_JAVASCRIPT_DSN
from libs.utils.http_utils import (astimezone_with_tz, easy_url, really_nice_time_format_with_tz,
    time_with_tz)


# Local and CDN Javascript/CSS libraries.  In order to codify the libraries in use we have these two
# classes.  All templates use these variables to populate any necessary assets loaded onto the page.
# At time of commenting the majority of common libraries


class LocalAssets:
    # These assets will be served from the server directly, and should not be minified.
    # Make sure any assets here match the apparent versions in CdnAssets for consistent debugging.
    # (it is very helpful to have real source code available to the IDE.)
    ANGULARJS = "/static/javascript/libraries/angular.js"
    BOOTSTRAP = "/static/javascript/libraries/bootstrap.js"
    BOOTSTRAP_INTEGRITY = "sha256-Cr6N6zNN4bp0OwTQOZ6Z66M2r+2dpy/EwKMCyZ+SOMg="
    BOOTSTRAP_CSS = "/static/css/libraries/bootstrap.css"
    BOOTSTRAP_CSS_INTEGRITY = "7e630d90c7234b0df1729f62b8f9e4bbfaf293d91a5a0ac46df25f2a6759e39a"
    BOOTSTRAP_TIMEPICKER = "/static/javascript/libraries/bootstrap-timepicker.js"
    BOOTSTRAP_TIMEPICKER_CSS = "/static/css/libraries/bootstrap-timepicker.css"
    BOOTSTRAP_DATETIMEPICKER = "/static/javascript/libraries/bootstrap-datetimepicker.js"
    BOOTSTRAP_DATETIMEPICKER_CSS = "/static/css/libraries/bootsetrap-datetimepicker.css"
    DATATABLES = "/static/javascript/libraries/datatables.js"
    DATATABLES_CSS = "/static/css/libraries/datatables.css"
    HANDLEBARS = "/static/javascript/libraries/handlebars.js"
    JQUERY = "/static/javascript/libraries/jquery.js"
    JQUERY_INTEGRITY = "sha256-TQrUBgXESZKk7rT8igyb7U9Y79tnhCTpKa+ryqxXaHc="
    LODASH = "/static/javascript/libraries/lodash.js"
    MOMENTJS = "/static/javascript/libraries/moment.js"


class CdnAssets:
    # These are the assets expected to be used in normal runtime, including most development scenarios.
    # Make sure any assets here match the versions in LocalAssets whenever they are updated
    ANGULARJS = "https://ajax.googleapis.com/ajax/libs/angularjs/1.8.2/angular.min.js"
    BOOTSTRAP = "https://cdn.jsdelivr.net/npm/bootstrap@3.3.7/dist/js/bootstrap.min.js"
    BOOTSTRAP_INTEGRITY = "sha384-Tc5IQib027qvyjSMfHjOMaLkfuWVxZxUPnCJA7l2mCWNIpG9mGCD8wGNIcPD7Txa"
    BOOTSTRAP_CSS = "https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css"
    BOOTSTRAP_CSS_INTEGRITY = "sha384-BVYiiSIFeK1dGmJRAkycuHAHRg32OmUcww7on3RYdg4Va+PmSTsz/K68vbdEjh4u"
    BOOTSTRAP_TIMEPICKER = "https://cdn.jsdelivr.net/npm/bootstrap-timepicker@0.5.2/js/bootstrap-timepicker.min.js"
    BOOTSTRAP_TIMEPICKER_CSS = "https://cdn.jsdelivr.net/npm/bootstrap-timepicker@0.5.2/css/bootstrap-timepicker.min.css"
    BOOTSTRAP_DATETIMEPICKER = "https://cdnjs.cloudflare.com/ajax/libs/eonasdan-bootstrap-datetimepicker/4.17.49/js/bootstrap-datetimepicker.min.js"
    BOOTSTRAP_DATETIMEPICKER_CSS = "https://cdnjs.cloudflare.com/ajax/libs/eonasdan-bootstrap-datetimepicker/4.17.49/css/bootstrap-datetimepicker.min.css"
    DATATABLES = "https://cdn.datatables.net/v/dt/dt-1.13.1/cr-1.6.1/r-2.4.0/datatables.min.js"
    DATATABLES_CSS = "https://cdn.datatables.net/v/dt/dt-1.13.1/cr-1.6.1/r-2.4.0/datatables.min.css"
    HANDLEBARS = "https://cdnjs.cloudflare.com/ajax/libs/handlebars.js/4.7.7/handlebars.min.js"
    JQUERY = "https://code.jquery.com/jquery-1.12.4.min.js"
    JQUERY_INTEGRITY = "sha256-ZosEbRLbNQzLpnKIkEdrPv7lOy9C27hHQ+Xp8a4MxAQ="
    LODASH = "https://cdn.jsdelivr.net/npm/lodash@4.17.21/lodash.min.js"
    MOMENTJS = "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.29.4/moment.min.js"


# set manually to local assets for debugging purposes only
# ASSETS = LocalAssets
ASSETS = CdnAssets


from jinja2.ext import Extension


class WhiteSpaceCollapser(Extension):
    """ Pretty simple Jinja2 extension that collapses whitespace what could possibly fgo wrong. """
    
    def preprocess(
        # self, source: str, name: t.Optional[str], filename: t.Optional[str] = None
        self, source, name, filename
    ) -> str:
        # all horizontal whitespace at the start and end of lines
        return re.sub(r'^[ \t]+|[ \t]+$', '', source, flags=re.MULTILINE)
        
        # collapse multiple successive identical whitespace characters
        # return re.sub(r'[ \t][ \t]+|\n\n+', '', source, flags=re.MULTILINE)
        
        # collapse most extended whitespace sequences down to just the first character, except
        # newlines, sequences of newlines are collapsed to a single newline. (and register returns)
        # has errors on at least the dashboard page
        # return re.sub(r'[ \t][ \t]+|[\n\r]+[ \t\n\r]*[\n\r]+', '', source, flags=re.MULTILINE)


def environment(**options):
    """ This enables us to use Django template tags like
    {% url “index” %} or {% static “path/to/static/file.js” %}
    in our Jinja2 templates.  """
    
    assert "autoescape" in options and options["autoescape"] is True
    
    # trunk-ignore(bandit/B701)
    env = Environment(
        line_comment_prefix="{#",
        comment_start_string="{% comment %}",
        comment_end_string="{% endcomment %}",
        trim_blocks=True,
        lstrip_blocks=True,
        extensions=[WhiteSpaceCollapser],
        **options
    )
    
    env.globals.update(
        {
            "static": staticfiles_storage.url,
            "url": reverse,
            "easy_url": easy_url,
            "astimezone_with_tz": astimezone_with_tz,
            "time_with_tz": time_with_tz,
            "really_nice_time_format_with_tz": really_nice_time_format_with_tz,
            "ASSETS": ASSETS,
            "SENTRY_JAVASCRIPT_DSN": SENTRY_JAVASCRIPT_DSN,
            "current_year": date.today().year,
        }
    )
    return env
