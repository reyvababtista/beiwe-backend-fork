from flask import Blueprint, flash, Markup, render_template

from authentication.admin_authentication import (authenticate_researcher_login,
    get_researcher_allowed_studies, get_researcher_allowed_studies_as_query_set,
    get_session_researcher, researcher_is_an_admin)
from config.constants import ALL_DATA_STREAMS

data_access_web_form = Blueprint('data_access_web_form', __name__)


@data_access_web_form.context_processor
def inject_html_params():
    # these variables will be accessible to every template rendering attached to the blueprint
    return {
        "allowed_studies": get_researcher_allowed_studies(),
        "users_by_study": participants_by_study(),
        "is_admin": researcher_is_an_admin()
    }


@data_access_web_form.route("/data_access_web_form", methods=['GET'])
@authenticate_researcher_login
def data_api_web_form_page():
    warn_researcher_if_hasnt_yet_generated_access_key(get_session_researcher())
    return render_template("data_api_web_form.html", ALL_DATA_STREAMS=ALL_DATA_STREAMS)


def warn_researcher_if_hasnt_yet_generated_access_key(researcher):
    if not researcher.access_key_id:
        msg = """You need to generate an <b>Access Key</b> and a <b>Secret Key </b> before you
        can download data. Go to <a href='/manage_credentials'> Manage Credentials</a> and click
        'Reset Data-Download API Access Credentials'. """
        flash(Markup(msg), 'danger')


def participants_by_study():
    # dict of {study ids : list of user ids}
    return {
        study.pk: list(study.participants.order_by("patient_id").values_list("patient_id", flat=True))
        for study in get_researcher_allowed_studies_as_query_set()
    }
