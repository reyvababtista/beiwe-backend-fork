import os

from flask import Blueprint, flash, redirect, abort

from database.study_models import Study
from libs.admin_authentication import authenticate_admin_study_access
from libs.sentry import make_error_sentry
from pipeline.boto_helpers import get_boto_client
from pipeline.index import create_one_job, refresh_data_access_credentials

data_pipeline_api = Blueprint('data_pipeline_api', __name__)
pipeline_region = os.getenv("pipeline_region", None)

@data_pipeline_api.route('/run-manual-code/<string:study_id>', methods=['POST'])
@authenticate_admin_study_access
def run_manual_code(study_id):
    """
    Create an AWS Batch job for the Study specified
    :param study_id: Primary key of a Study
    """
    
    # Get the object ID of the study, used in the pipeline
    query = Study.objects.filter(pk=study_id)
    if not query.exists():
        return abort(404)
    object_id = query.get().object_id

    if not pipeline_region:
        flash('This server is not correctly configured to support data pipeline processes.', category='danger')
        return redirect('/data-pipeline/{:s}'.format(study_id))
        
    error_sentry = make_error_sentry("data", tags={"pipeline_frequency": "manually"})
    # Get new data access credentials for the manual user, submit a manual job, display message
    # Report all errors to sentry including DataPipelineNotConfigured errors.
    with error_sentry:
        ssm_client = get_boto_client('ssm', pipeline_region)
        refresh_data_access_credentials('manually', ssm_client=ssm_client)
        batch_client = get_boto_client('batch', pipeline_region)
        create_one_job('manually', object_id, batch_client)
        flash('Data pipeline code successfully initiated!', 'success')
    
    if error_sentry.errors:
        flash('An unknown error occurred when trying to run this task.', category='danger')
        print error_sentry
    
    return redirect('/data-pipeline/{:s}'.format(study_id))
