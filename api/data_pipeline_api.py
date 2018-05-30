from flask import Blueprint, flash, redirect

from database.study_models import Study
from libs.admin_authentication import authenticate_admin_study_access
from libs.sentry import make_error_sentry
from pipeline.boto_helpers import get_aws_object_names
from pipeline.index import create_one_job, refresh_data_access_credentials


data_pipeline_api = Blueprint('data_pipeline_api', __name__)


@data_pipeline_api.route('/run-manual-code/<string:study_id>', methods=['POST'])
@authenticate_admin_study_access
def run_manual_code(study_id):
    """
    Create an AWS Batch job for the Study specified
    :param study_id: Primary key of a Study
    """
    
    # Get the object ID of the study, used in the pipeline
    object_id = Study.objects.get(pk=study_id).object_id
    error_sentry = make_error_sentry("data", tags={"pipeline_frequency": "manually"})
    
    with error_sentry:
        # Get new data access credentials for the manual user
        aws_object_names = get_aws_object_names()
        refresh_data_access_credentials('manually', aws_object_names)
        
        # Submit a manual job
        create_one_job('manually', object_id)
        
        # The success message gets displayed to the user upon redirect
        flash('Data pipeline code successfully initiated!', 'success')
    
    if error_sentry.errors:
        flash('An unknown error occurred when trying to run this task.', 'danger')
    
    return redirect('/data-pipeline/{:s}'.format(study_id))
