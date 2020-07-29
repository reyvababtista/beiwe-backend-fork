from flask import Blueprint, flash, Markup, redirect, render_template, request, session

from authentication import admin_authentication
from authentication.admin_authentication import (authenticate_researcher_login,
    authenticate_researcher_study_access, get_researcher_allowed_studies,
    get_researcher_allowed_studies_as_query_set, get_researcher_api_keys, researcher_is_an_admin,
    SESSION_NAME)
from database.security_models import ApiKey
from database.study_models import Study
from database.user_models import Participant, Researcher
from libs.push_notification_config import check_firebase_instance
from libs.security import check_password_requirements

admin_pages = Blueprint('admin_pages', __name__)


@admin_pages.context_processor
def inject_html_params():
    # these variables will be accessible to every template rendering attached to the blueprint
    return {
        "allowed_studies": get_researcher_allowed_studies(),
        "is_admin": researcher_is_an_admin(),
    }


@admin_pages.route('/choose_study', methods=['GET'])
@authenticate_researcher_login
def choose_study():
    allowed_studies = get_researcher_allowed_studies_as_query_set()

    # If the admin is authorized to view exactly 1 study, redirect to that study
    if allowed_studies.count() == 1:
        return redirect('/view_study/{:d}'.format(allowed_studies.values_list('pk', flat=True).get()))

    # Otherwise, show the "Choose Study" page

    return render_template(
        'choose_study.html',
        studies=[obj.as_unpacked_native_python() for obj in allowed_studies],
        allowed_studies=get_researcher_allowed_studies(),
        is_admin=researcher_is_an_admin()
    )


@admin_pages.route('/view_study/<string:study_id>', methods=['GET'])
@authenticate_researcher_study_access
def view_study(study_id=None):
    study = Study.objects.get(pk=study_id)
    participants = study.participants.all()

    # creates dicts of Custom Fields and Interventions to be easily accessed in the template
    for p in participants:
        p.field_dict = participant_tags(p)
        p.intervention_dict = {tag.intervention.name: tag.date for tag in p.intervention_dates.all()}

    return render_template(
        'view_study.html',
        study=study,
        participants=participants,
        audio_survey_ids=study.get_survey_ids_and_object_ids('audio_survey'),
        image_survey_ids=study.get_survey_ids_and_object_ids('image_survey'),
        tracking_survey_ids=study.get_survey_ids_and_object_ids('tracking_survey'),
        # these need to be lists because they will be converted to json.
        study_fields=list(study.fields.all().values_list('field_name', flat=True)),
        interventions=list(study.interventions.all().values_list("name", flat=True)),
        page_location='study_landing',
        study_id=study_id,
        push_notifications_enabled=check_firebase_instance(require_android=True) or
                                   check_firebase_instance(require_ios=True),
    )


"""########################## Login/Logoff ##################################"""


@admin_pages.route("/logout")
def logout():
    admin_authentication.logout_researcher()
    return redirect("/")


@admin_pages.route('/manage_credentials')
@authenticate_researcher_login
def manage_credentials():
    # Todo (CD): Create a section for managing API keys
    return render_template('manage_credentials.html',
                           allowed_studies=get_researcher_allowed_studies(),
                           is_admin=researcher_is_an_admin(),
                           api_keys=get_researcher_api_keys(),
                           api_keys_enabled=[k for k in get_researcher_api_keys() if k.is_active],
                           api_keys_disabled=[k for k in get_researcher_api_keys() if not k.is_active])


@admin_pages.route('/reset_admin_password', methods=['POST'])
@authenticate_researcher_login
def reset_admin_password():
    username = session[SESSION_NAME]
    current_password = request.values['current_password']
    new_password = request.values['new_password']
    confirm_new_password = request.values['confirm_new_password']

    if not Researcher.check_password(username, current_password):
        flash("The Current Password you have entered is invalid", 'danger')
        return redirect('/manage_credentials')
    if not check_password_requirements(new_password, flash_message=True):
        return redirect("/manage_credentials")
    if new_password != confirm_new_password:
        flash("New Password does not match Confirm New Password", 'danger')
        return redirect('/manage_credentials')

    # todo: sanitize password?
    Researcher.objects.get(username=username).set_password(new_password)
    flash("Your password has been reset!", 'success')
    return redirect('/manage_credentials')


@admin_pages.route('/reset_download_api_credentials', methods=['POST'])
@authenticate_researcher_login
def reset_download_api_credentials():
    researcher = Researcher.objects.get(username=session[SESSION_NAME])
    access_key, secret_key = researcher.reset_access_credentials()

    msg = """<h3>Your Data-Download API access credentials have been reset!</h3>
        <p>Your new <b>Access Key</b> is:
          <div class="container-fluid">
            <textarea rows="1" cols="85" readonly="readonly" onclick="this.focus();this.select()">%s</textarea></p>
          </div>
        <p>Your new <b>Secret Key</b> is:
          <div class="container-fluid">
            <textarea rows="1" cols="85" readonly="readonly" onclick="this.focus();this.select()">%s</textarea></p>
          </div>
        <p>Please record these somewhere; they will not be shown again!</p>""" \
          % (access_key, secret_key)
    flash(Markup(msg), 'warning')
    return redirect("/manage_credentials")


def participant_tags(p: Participant):
    return {tag.field.field_name: tag.value for tag in p.field_values.all()}


@admin_pages.route('/new_api_key', methods=['POST'])
@authenticate_researcher_login
def new_api_key():
    tableau_api_permission = 'api_permission' in request.values
    readable_name = request.values.get("readable_name", "")
    researcher = Researcher.objects.get(username=session[SESSION_NAME])
    api_key = ApiKey.generate(researcher=researcher, has_tableau_api_permissions=tableau_api_permission, readable_name=readable_name)
    msg = """<h3>New Data-Download API credentials have been generated for you!</h3>
        <p>Your new <b>Access Key</b> is:
          <div class="container-fluid">
            <textarea rows="1" cols="85" readonly="readonly" onclick="this.focus();this.select()">%s</textarea></p>
          </div>
        <p>Your new <b>Secret Key</b> is:
          <div class="container-fluid">
            <textarea rows="1" cols="85" readonly="readonly" onclick="this.focus();this.select()">%s</textarea></p>
          </div>
        <p>Please record these somewhere; This secret key will not be shown again!</p>""" \
          % (api_key.access_key_id, api_key.access_key_secret_plaintext)
    api_key.save()
    flash(Markup(msg), 'warning')
    return redirect("/manage_credentials")


# todo verify researcher owns that api key
@admin_pages.route('/disable_api_key', methods=['POST'])
@authenticate_researcher_login
def disable_api_key():
    if "api_key_id" not in request.values:
        flash(Markup("No API key specified"), 'warning')
        return redirect("/manage_credentials")
    api_key_id = request.values["api_key_id"]
    api_key_query = ApiKey.objects.filter(access_key_id=api_key_id)
    if not api_key_query.exists():
        flash(Markup("No matching API key found to disable"), 'warning')
        return redirect("/manage_credentials")
    api_key = api_key_query[0]
    if not api_key.is_active:
        flash("That API key has already been disabled", 'warning')
        return redirect("/manage_credentials")
    api_key.is_active = False
    api_key.save()
    # flash("The API key %s is now disabled" % str(api_key.access_key_id), 'warning')
    return redirect("/manage_credentials")

