from datetime import date
from config.settings import SENTRY_JAVASCRIPT_DSN
from constants.common_constants import RUNNING_TEST_OR_IN_A_SHELL

from database.study_models import Study
from libs.internal_types import ResearcherRequest

# set this to false to enable local javascript sources
FORCE_CDN_JAVASCRIPT = True


class LocalAssets:
    ANGULARJS = "/static/javascript/libraries/angular.js"
    BOOTSTRAP = "/static/javascript/libraries/bootstrap.js"
    BOOTSTRAP_INTEGRITY = "sha256-Cr6N6zNN4bp0OwTQOZ6Z66M2r+2dpy/EwKMCyZ+SOMg="
    BOOTSTRAP_CSS = "/static/css/libraries/bootstrap.css"
    BOOTSTRAP_CSS_INTEGRITY = "7e630d90c7234b0df1729f62b8f9e4bbfaf293d91a5a0ac46df25f2a6759e39a"
    BOOTSTRAP_TIMEPICKER = "/static/javascript/libraries/bootstrap-timepicker.js"
    BOOTSTRAP_TIMEPICKER_CSS = "/static/css/libraries/bootstrap-timepicker.css"
    DATATABLES = "/static/javascript/libraries/datatables.js"
    DATATABLES_CSS = "/static/css/libraries/datatables.css"
    HANDLEBARS = "/static/javascript/libraries/handlebars.js"
    JQUERY = "/static/javascript/libraries/jquery.js"
    JQUERY_INTEGRITY = "sha256-TQrUBgXESZKk7rT8igyb7U9Y79tnhCTpKa+ryqxXaHc="
    LODASH = "/static/javascript/libraries/lodash.js"
    MOMENTJS = "/static/javascript/libraries/moment.js"


class CdnAssets:
    ANGULARJS = "https://ajax.googleapis.com/ajax/libs/angularjs/1.8.2/angular.min.js"
    BOOTSTRAP = "https://cdn.jsdelivr.net/npm/bootstrap@3.3.7/dist/js/bootstrap.min.js"
    BOOTSTRAP_INTEGRITY = "sha384-Tc5IQib027qvyjSMfHjOMaLkfuWVxZxUPnCJA7l2mCWNIpG9mGCD8wGNIcPD7Txa"
    BOOTSTRAP_CSS = "https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css"
    BOOTSTRAP_CSS_INTEGRITY = "sha384-BVYiiSIFeK1dGmJRAkycuHAHRg32OmUcww7on3RYdg4Va+PmSTsz/K68vbdEjh4u"
    BOOTSTRAP_TIMEPICKER = "https://cdn.jsdelivr.net/npm/bootstrap-timepicker@0.5.2/js/bootstrap-timepicker.min.js"
    BOOTSTRAP_TIMEPICKER_CSS = "https://cdn.jsdelivr.net/npm/bootstrap-timepicker@0.5.2/css/bootstrap-timepicker.min.css"
    DATATABLES = "https://cdn.datatables.net/v/dt/dt-1.13.1/cr-1.6.1/r-2.4.0/datatables.min.js"
    DATATABLES_CSS = "https://cdn.datatables.net/v/dt/dt-1.13.1/cr-1.6.1/r-2.4.0/datatables.min.css"
    HANDLEBARS = "https://cdnjs.cloudflare.com/ajax/libs/handlebars.js/4.7.7/handlebars.min.js"
    JQUERY = "https://code.jquery.com/jquery-1.12.4.min.js"
    JQUERY_INTEGRITY = "sha256-ZosEbRLbNQzLpnKIkEdrPv7lOy9C27hHQ+Xp8a4MxAQ="
    LODASH = "https://cdn.jsdelivr.net/npm/lodash@4.17.21/lodash.min.js"
    MOMENTJS = "https://cdnjs.cloudflare.com/ajax/libs/moment.js/2.29.4/moment.min.js"


# When running locally we use the local copies of the libraries
ASSETS = CdnAssets if not RUNNING_TEST_OR_IN_A_SHELL else LocalAssets
ASSETS = CdnAssets if FORCE_CDN_JAVASCRIPT else LocalAssets

print("this thing:", ASSETS.__name__)

def researcher_context_processor(request: ResearcherRequest):
    # Common assets used everywhere
    ret = {
        "SENTRY_JAVASCRIPT_DSN": SENTRY_JAVASCRIPT_DSN,
        "current_year": date.today().year,
        "ASSETS": ASSETS,
    }
    
    # if it is a researcher endpoint (aka has the admin or researcher or study/survey authentication
    # decorators) then we need most of these variables available in the template.
    if hasattr(request, "session_researcher"):
        # the studies dropdown is on almost all pages.
        allowed_studies_kwargs = {} if request.session_researcher.site_admin else \
            {"study_relations__researcher": request.session_researcher}
        
        ret["allowed_studies"] = [
            study_info_dict for study_info_dict in Study.get_all_studies_by_name()
            .filter(**allowed_studies_kwargs).values("name", "object_id", "id", "is_test")
        ]
        ret["is_admin"] = request.session_researcher.is_an_admin()
        ret["site_admin"] = request.session_researcher.site_admin
        ret["session_researcher"] = request.session_researcher
    from pprint import pprint
    pprint(ret["allowed_studies"])
    return ret
