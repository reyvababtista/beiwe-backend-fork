from __future__ import print_function

from flask import Blueprint, render_template

from database.study_models import Study
from libs.admin_authentication import authenticate_admin_study_access

dashboard_api = Blueprint('dashboard_api', __name__)


@dashboard_api.route("/dashboard/<string:study_id>", methods=["GET"])
@authenticate_admin_study_access
def dashboard_page(study_id=None):
    return render_template(
        'dashboard/dashboard.html',
        study_name=Study.objects.filter(pk=study_id).values_list("name", flat=True).get()
    )

# @dashboard_api.route("/dashboard/<string:study_id>", methods=["GET", "POST"])
# @authenticate_admin_study_access
# def thang():
#     pass