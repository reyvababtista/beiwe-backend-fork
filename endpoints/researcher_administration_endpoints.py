from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from authentication.admin_authentication import (abort, assert_admin, assert_researcher_under_admin,
    authenticate_admin)
from constants.message_strings import MFA_RESET_BAD_PERMISSIONS, NEW_PASSWORD_N_LONG
from constants.user_constants import ResearcherRole
from database.study_models import Study
from database.user_models_researcher import Researcher, StudyRelation
from libs.endpoint_helpers.researcher_helpers import get_administerable_researchers
from libs.endpoint_helpers.study_helpers import get_administerable_studies_by_name
from libs.endpoint_helpers.system_admin_helpers import mfa_clear_allowed
from libs.http_utils import easy_url
from libs.internal_types import ResearcherRequest


@require_GET
@authenticate_admin
def manage_researchers_page(request: ResearcherRequest):
    # get the study names that each user has access to, but only those that the current admin  also
    # has access to.
    if request.session_researcher.site_admin:
        session_ids = Study.objects.exclude(deleted=True).values_list("id", flat=True)
    else:
        session_ids = request.session_researcher.\
            study_relations.filter(study__deleted=False).values_list("study__id", flat=True)
    
    researcher_list = []
    for researcher in get_administerable_researchers(request):
        allowed_studies = Study.get_all_studies_by_name().filter(
            study_relations__researcher=researcher, study_relations__study__in=session_ids,
        ).values_list('name', flat=True)
        researcher_list.append(
            ({'username': researcher.username, 'id': researcher.id}, list(allowed_studies))
        )
    return render(request, 'manage_researchers.html', context=dict(admins=researcher_list))


@require_http_methods(['GET', 'POST'])
@authenticate_admin
def administrator_edit_researcher_page(request: ResearcherRequest, researcher_pk: int):
    """ The page and various permissions logic for the edit researcher page. """
    session_researcher = request.session_researcher
    edit_researcher = Researcher.objects.get(pk=researcher_pk)
    
    # site admins can force a password reset on study admins, but not other site admins
    editable_password =\
        not edit_researcher.username == session_researcher.username and not edit_researcher.site_admin
    
    # if the session researcher is not a site admin then we need to restrict password editing
    # to only researchers that are not study_admins anywhere.
    if not session_researcher.site_admin:
        editable_password = editable_password and not edit_researcher.is_study_admin()
    
    # edit_study_info is a list of tuples of (study relationship, whether that study is editable by
    # the current session admin, and the study itself.)
    visible_studies = session_researcher.get_visible_studies_by_name()
    if edit_researcher.site_admin:
        # if the session admin is a site admin then we can skip the complex logic
        edit_study_info = [("Site Admin", True, study) for study in visible_studies]
    else:
        # When the session admin is just a study admin then we need to determine if the study that
        # the session admin can see is also one they are an admin on so we can display buttons.
        administerable_studies = set(get_administerable_studies_by_name(request).values_list("pk", flat=True))
        
        # We need the overlap of the edit_researcher studies with the studies visible to the session
        # admin, and we need those relationships for display purposes on the page.
        edit_study_relationship_map = {
            study_id: relationship.replace("_", " ").title()
            for study_id, relationship in edit_researcher.study_relations
                .filter(study__in=visible_studies).values_list("study_id", "relationship")
        }
        # get the relevant studies, populate with relationship, editability, and the study.
        edit_study_info = [
            (edit_study_relationship_map[study.id], study.id in administerable_studies, study)
            for study in visible_studies.filter(pk__in=edit_study_relationship_map.keys())
        ]
    
    return render(
        request, 'edit_researcher.html',
        dict(
            edit_researcher=edit_researcher,
            edit_study_info=edit_study_info,
            all_studies=get_administerable_studies_by_name(request),
            editable_password=editable_password,
            editable_mfa=mfa_clear_allowed(session_researcher, edit_researcher),
            redirect_url=easy_url('researcher_administration_endpoints.administrator_edit_researcher_page', researcher_pk),
            is_self=edit_researcher.id == session_researcher.id,
        )
    )


@require_POST
@authenticate_admin
def administrator_reset_researcher_mfa(request: ResearcherRequest, researcher_id: int):
    # TODO: actually build and test this
    researcher = get_object_or_404(Researcher, pk=researcher_id)
    
    if mfa_clear_allowed(request.session_researcher, researcher):
        researcher.clear_mfa()
        messages.warning(request, f"MFA token cleared for researcher {researcher.username}.")
    else:
        messages.warning(request, MFA_RESET_BAD_PERMISSIONS)
        return abort(403)
    return redirect(easy_url('researcher_administration_endpoints.administrator_edit_researcher_page', researcher_id))


@require_POST
@authenticate_admin
def elevate_researcher_to_study_admin(request: ResearcherRequest):
    researcher_pk = request.POST.get("researcher_id", None)
    # some extra validation on the researcher id
    try:
        int(researcher_pk)
    except ValueError:
        return abort(400)
    
    study_pk = request.POST.get("study_id", None)
    assert_admin(request, study_pk)
    edit_researcher = get_object_or_404(Researcher, pk=researcher_pk)
    study = get_object_or_404(Study, pk=study_pk)
    assert_researcher_under_admin(request, edit_researcher, study)
    if edit_researcher.site_admin:
        return abort(403)
    StudyRelation.objects.filter(researcher=edit_researcher, study=study) \
        .update(relationship=ResearcherRole.study_admin)
    
    return redirect(
        request.POST.get("redirect_url", None) or f'/edit_researcher/{researcher_pk}'
    )


@require_POST
@authenticate_admin
def demote_study_admin_to_researcher(request: ResearcherRequest):
    # FIXME: this endpoint does not test for site admin cases correctly, the test passes but is
    # wrong. Behavior is fine because it has no relevant side effects except for the know bug where
    # site admins need to be manually added to a study before being able to download data.
    researcher_pk = request.POST.get("researcher_id")
    study_pk = request.POST.get("study_id")
    assert_admin(request, study_pk)
    # assert_researcher_under_admin() would fail here...
    StudyRelation.objects.filter(
        researcher=Researcher.objects.get(pk=researcher_pk),
        study=Study.objects.get(pk=study_pk),
    ).update(relationship=ResearcherRole.researcher)
    return redirect(request.POST.get("redirect_url", None) or f'/edit_researcher/{researcher_pk}')


@require_http_methods(['GET', 'POST'])
@authenticate_admin
def create_new_researcher(request: ResearcherRequest):
    # FIXME: get rid of dual endpoint pattern, it is a bad idea.
    if request.method == 'GET':
        return render(request, 'create_new_researcher.html')
    
    # Drop any whitespace or special characters from the username (restrictive, alphanumerics-only)
    username = ''.join(c for c in request.POST.get('admin_id', '') if c.isalnum())
    password = request.POST.get('password', '')
    
    if Researcher.objects.filter(username=username).exists():
        messages.error(request, f"There is already a researcher with username {username}")
        return redirect('/create_new_researcher')
    
    if len(password) < 8:
        messages.error(request, NEW_PASSWORD_N_LONG.format(length=8))
        return redirect('/create_new_researcher')
    else:
        researcher = Researcher.create_with_password(username, password)
    return redirect(f'/edit_researcher/{researcher.pk}')
