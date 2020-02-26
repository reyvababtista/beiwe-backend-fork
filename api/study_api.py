from datetime import datetime

from django.db.models import ProtectedError
from flask import Blueprint, render_template, request, abort, redirect, flash

from config import constants
from database.schedule_models import Intervention, InterventionDate
from database.study_models import Study, StudyField
from database.user_models import ParticipantFieldValue, Participant
from libs.admin_authentication import authenticate_researcher_study_access, get_session_researcher, \
    get_researcher_allowed_studies, researcher_is_an_admin

study_api = Blueprint('study_api', __name__)


@study_api.route('/view_study/<string:study_id>/edit_participant/<string:participant_id>', methods=['GET', 'POST'])
@authenticate_researcher_study_access
def edit_participant(study_id, participant_id):
    try:
        participant = Participant.objects.get(pk=participant_id)
    except Participant.DoesNotExist:
        return abort(404)

    study = participant.study

    if request.method == 'GET':
        return render_template(
            'edit_participant.html',
            participant=participant,
            study=study,
            date_format=constants.REDUCED_API_TIME_FORMAT,
            allowed_studies=get_researcher_allowed_studies(),
        )

    for intervention in study.interventions.all():
        input_id = f"intervention{intervention.id}"
        intervention_date = participant.intervention_dates.get(intervention=intervention)
        intervention_date.date = datetime.strptime(request.values.get(input_id, None), constants.REDUCED_API_TIME_FORMAT).date()
        intervention_date.save()

    for field in study.fields.all():
        input_id = f"field{field.id}"
        field_value = participant.field_values.get(field=field)
        field_value.value = request.values.get(input_id, None)
        field_value.save()

    flash('Successfully editted participant {}.'.format(participant.patient_id), 'success')
    return redirect('/view_study/{:d}/edit_participant/{:d}'.format(study.id, participant.id))


@study_api.route('/interventions/<string:study_id>', methods=['GET', 'POST'])
@authenticate_researcher_study_access
def interventions(study_id=None):
    study = Study.objects.get(pk=study_id)
    researcher = get_session_researcher()
    readonly = True if not researcher.check_study_admin(study_id) and not researcher.site_admin else False

    if request.method == 'GET':
        return render_template(
            'study_interventions.html',
            study=study,
            interventions=study.interventions.all(),
            readonly=readonly,
            allowed_studies=get_researcher_allowed_studies(),
        )

    if readonly:
        abort(403)

    new_intervention = request.values.get('new_intervention', None)
    if new_intervention:
        intervention, _ = Intervention.objects.get_or_create(study=study, name=new_intervention)
        for participant in study.participants.all():
            InterventionDate.objects.get_or_create(participant=participant, intervention=intervention)

    return redirect('/interventions/{:d}'.format(study.id))


@study_api.route('/delete_intervention/<string:study_id>', methods=['POST'])
@authenticate_researcher_study_access
def delete_intervention(study_id=None):
    study = Study.objects.get(pk=study_id)
    researcher = get_session_researcher()
    readonly = True if not researcher.check_study_admin(study_id) and not researcher.site_admin else False
    if readonly:
        abort(403)

    intervention_id = request.values.get('intervention')
    if intervention_id:
        try:
            intervention = Intervention.objects.get(id=intervention_id)
        except Intervention.DoesNotExist:
            intervention = None
        try:
            if intervention:
                intervention.delete()
        except ProtectedError:
            flash("This Intervention can not be removed because it is already in use", 'danger')

    return redirect('/interventions/{:d}'.format(study.id))


@study_api.route('/edit_intervention/<string:study_id>', methods=['POST'])
@authenticate_researcher_study_access
def edit_intervention(study_id=None):
    study = Study.objects.get(pk=study_id)
    researcher = get_session_researcher()
    readonly = True if not researcher.check_study_admin(study_id) and not researcher.site_admin else False
    if readonly:
        abort(403)

    intervention_id = request.values.get('intervention_id', None)
    new_name = request.values.get('edit_intervention', None)
    if intervention_id:
        try:
            intervention = Intervention.objects.get(id=intervention_id)
        except Intervention.DoesNotExist:
            intervention = None
        if intervention and new_name:
            intervention.name = new_name
            intervention.save()

    return redirect('/interventions/{:d}'.format(study.id))


@study_api.route('/study_fields/<string:study_id>', methods=['GET', 'POST'])
@authenticate_researcher_study_access
def study_fields(study_id=None):
    study = Study.objects.get(pk=study_id)
    researcher = get_session_researcher()
    readonly = True if not researcher.check_study_admin(study_id) and not researcher.site_admin else False

    if request.method == 'GET':
        return render_template(
            'study_custom_fields.html',
            study=study,
            fields=study.fields.all(),
            readonly=readonly,
            allowed_studies=get_researcher_allowed_studies(),
            is_admin=researcher_is_an_admin(),
        )

    if readonly:
        abort(403)

    new_field = request.values.get('new_field', None)
    if new_field:
        study_field, _ = StudyField.objects.get_or_create(study=study, field_name=new_field)
        for participant in study.participants.all():
            ParticipantFieldValue.objects.create(participant=participant, field=study_field)

    return redirect('/study_fields/{:d}'.format(study.id))


@study_api.route('/delete_field/<string:study_id>', methods=['POST'])
@authenticate_researcher_study_access
def delete_field(study_id=None):
    study = Study.objects.get(pk=study_id)
    researcher = get_session_researcher()
    readonly = True if not researcher.check_study_admin(study_id) and not researcher.site_admin else False
    if readonly:
        abort(403)

    field = request.values.get('field', None)
    if field:
        try:
            study_field = StudyField.objects.get(study=study, id=field)
        except StudyField.DoesNotExist:
            study_field = None

        try:
            if study_field:
                study_field.delete()
        except ProtectedError:
            flash("This field can not be removed because it is already in use", 'danger')

    return redirect('/study_fields/{:d}'.format(study.id))


@study_api.route('/edit_custom_field/<string:study_id>', methods=['POST'])
@authenticate_researcher_study_access
def edit_custom_field(study_id=None):
    study = Study.objects.get(pk=study_id)
    researcher = get_session_researcher()
    readonly = True if not researcher.check_study_admin(
        study_id) and not researcher.site_admin else False
    if readonly:
        abort(403)

    field_id = request.values.get("field_id")
    new_field_name = request.values.get("edit_custom_field")
    if field_id:
        try:
            field = StudyField.objects.get(id=field_id)
        except StudyField.DoesNotExist:
            field = None
        if field and new_field_name:
            field.field_name = new_field_name
            field.save()

    return redirect('/study_fields/{:d}'.format(study.id))

