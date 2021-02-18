#! /usr/bin/bash

# This script allows a single-file location for storing all your creddentials and settings.
# Copy this script file, and populate this script with the contents of the files you have already generated.
# Leave this file in the cluster_management folder of the repository.

tee ./environment_configuration/name-o-your-eb-application_beiwe_environment_variables.json << EOF
{
 "DOMAIN": "my.beiwe.domain.tld",
 "SENTRY_ELASTIC_BEANSTALK_DSN": "",
 "SENTRY_DATA_PROCESSING_DSN": "",
 "SENTRY_JAVASCRIPT_DSN": ""
}
EOF

tee ./environment_configuration/name-o-your-eb-application_database_credentials.json << EOF
{
 "RDS_USERNAME": ""
 "RDS_PASSWORD": ""
 "RDS_DB_NAME": ""
}
EOF

tee ./environment_configuration/name-o-your-eb-application_finalized_settings.json << EOF
{
 "DOMAIN_NAME":: ""
 "SYSADMIN_EMAILS": ""
 "SENTRY_ELASTIC_BEANSTALK_DSN": ""
 "SENTRY_DATA_PROCESSING_DSN": ""
 "SENTRY_JAVASCRIPT_DSN": ""
 "RDS_USERNAME": ""
 "RDS_PASSWORD": ""
 "RDS_DB_NAME": ""
 "RDS_HOSTNAME": ""
 "FLASK_SECRET_KEY": ""
 "S3_BUCKET": ""
 "BEIWE_SERVER_AWS_ACCESS_KEY_ID": ""
 "BEIWE_SERVER_AWS_SECRET_ACCESS_KEY": ""
}
EOF

tee ./environment_configuration/name-o-your-eb-application_remote_db_env.py << EOF
import os
os.environ['DOMAIN_NAME'] = ""
os.environ['SYSADMIN_EMAILS'] = ""
os.environ['SENTRY_ELASTIC_BEANSTALK_DSN'] = ""
os.environ['SENTRY_DATA_PROCESSING_DSN'] = ""
os.environ['SENTRY_JAVASCRIPT_DSN'] = ""
os.environ['RDS_USERNAME'] = ""
os.environ['RDS_PASSWORD'] = ""
os.environ['RDS_DB_NAME'] = ""
os.environ['RDS_HOSTNAME'] = ""
os.environ['FLASK_SECRET_KEY'] = ""
os.environ['S3_BUCKET'] = ""
os.environ['BEIWE_SERVER_AWS_ACCESS_KEY_ID'] = ""
os.environ['BEIWE_SERVER_AWS_SECRET_ACCESS_KEY'] = ""
EOF

tee ./environment_configuration/name-o-your-eb-application_server_settings.json << EOF
{
 "WORKER_SERVER_INSTANCE_TYPE": "t3.large",
 "MANAGER_SERVER_INSTANCE_TYPE": "t3.medium",
 "ELASTIC_BEANSTALK_INSTANCE_TYPE": "t3.medium",
 "DB_SERVER_TYPE": "m5.large"
}
EOF

# this one contains personal file paths and resource names.  DEPLOYMENT_KEY_FILE_PATH should be absolute.
tee ./general_configuration/global_configuration.json << EOF
{
  "DEPLOYMENT_KEY_NAME": ""
  "DEPLOYMENT_KEY_FILE_PATH": ""
  "VPC_ID": ""
  "AWS_REGION": ""
  "SYSTEM_ADMINISTRATOR_EMAIL": ""
}
EOF

tee ./general_configuration/aws_credentials.json << EOF
{
  "AWS_ACCESS_KEY_ID" : ""
  "AWS_SECRET_ACCESS_KEY" : ""
}
EOF

time python launch_script.py -terminate-processing-servers << EOF
beiweCluster-staging
EOF

time python launch_script.py -create-manager << EOF
name-o-your-eb-application
EOF

# if you want to deploy a branch other than master to a data processing server follow this pattern:
# 1) checkout onto the desired branch
# 2) add the 'export DEV_BRANCH="branch_name"' with branch_name a set to the branch you are on
# 3) add the -dev command line option to the script in addition to the desired command
# Note: the -dev command line option may cause extra debug output to occur, this is normal and intentional.

# Example:
# export DEV_BRANCH="development"
# time python launch_script.py -dev -create-manager << EOF
# name-o-your-eb-application
# EOF
