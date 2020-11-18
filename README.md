# Setup instructions

## Configuring SSL
Because Beiwe often deals with sensitive data covered under HIPAA, it's important to add an SSL certificate so that web traffic is encrypted with HTTPS.

The setup script [uses AWS Certificate Manager to generate an SSL certificate](http://docs.aws.amazon.com/acm/latest/userguide/gs-acm-request.html).  AWS Certificate Manager [will check that you control the domain by sending verification emails](http://docs.aws.amazon.com/acm/latest/userguide/gs-acm-validate.html) to the email addresses in the domain's WHOIS listing.

## Configuring Firebase
To initialize the Firebase SDK, [generate a private key file](https://firebase.google.com/docs/admin/setup#initialize-sdk).
Rename the file firebase_cloud_messaging_credentials.json and place it in the project root.

***

# Configuration settings

All the settings listed here can be found either in the constants file or in the
config/settings.py file, or can have an environment variable set for them.

Optional Settings
if an environment variable is provided for any of these they will override the default
value.  More information is available in the constants and config/settings.py files in the
config directory.

```
    DEFAULT_S3_RETRIES - the number of retries on attempts to connect to AWS S3
        default: 1
    CONCURRENT_NETWORK_OPS - the number of concurrent network operations throughout the codebase
        default: 10
    FILE_PROCESS_PAGE_SIZE - the number of files pulled in for processing at a time
        default: 250
    ASYMMETRIC_KEY_LENGTH - length of key files used in the app
        default: 2048
    ITERATIONS - PBKDF2 iteration count for passwords
        default: 1000
```

Mandatory Settings
If any of these are not provided, Beiwe will not run, empty and None values are
considered invalid  Additional documentation can be found in config/setting.pys.

```
    FLASK_SECRET_KEY - a unique, cryptographically secure string
    AWS_ACCESS_KEY_ID - AWS access key for S3
    AWS_SECRET_ACCESS_KEY - AWS secret key for S3
    S3_BUCKET - the bucket for storing app-generated data
    E500_EMAIL_ADDRESS - the source email address for 500 error alerts
    OTHER_EMAIL_ADDRESS - the source email address for other error events
    SYSADMIN_EMAILS - a comma separated list of email addresses for recipients of error reports. (whitespace before and after addresses will be ignored)
    RDS_DB_NAME - postgress database name (the name of the database inside of postgres)
    RDS_USERNAME - database username
    RDS_PASSWORD - database password
    RDS_HOSTNAME - database IP address or url
    S3_ACCESS_CREDENTIALS_USER - the user id for s3 access for your deployment
    S3_ACCESS_CREDENTIALS_KEY - the secret key for s3 access for your deployment
```

***

# Development setup
How to set up beiwe-backend running on a development machine (NOT a production instance!  For a production instance,
see https://github.com/onnela-lab/beiwe-backend/wiki/Deployment-Instructions---Scalable-Deployment)

1. `sudo apt-get update;sudo apt-get install postgresql python-psycopg2 libpq-dev`
2. `pip install -r requirements.txt`
3. Create a file for your environment variables that contains at least these:
    ```
    export DOMAIN_NAME="localhost://8080"
    export FLASK_SECRET_KEY="asdf"
    export S3_BUCKET="a"
    export SYSADMIN_EMAILS="sysadmin@localhst"
    ```
    I usually store it at `private/environment.sh`.  Load up these environment variables by running `source private/environment.sh` at the Bash prompt.

### Local Celery setup
1. Install RabbitMQ (https://docs.celeryproject.org/en/latest/getting-started/brokers/rabbitmq.html#broker-rabbitmq)
    1. Edit `/etc/rabbitmq/rabbitmq-env.conf` and add the line `NODE_PORT=50000`
    2. Restart RabbitMQ like this in the Bash shell: `time sudo service rabbitmq-server restart` (`time` isn't necessary, but it tells you how long the command took to execute)
2. `pip install -r requirements_data_processing.txt` (this will install Celery using Pip)
3. Create a file called `manager_ip` in the top level of this `beiwe-backend` repo, and enter two lines in it:
    ```
    127.0.0.1:50000
    [PASSWORD]
    ```
    Where the password is the one you set when setting up RabbitMQ
4. `sudo rabbitmqctl set_permissions -p / beiwe ".*" ".*" ".*"`
5. Set the filename of your Firebase credentials JSON file in `libs/push_notifications.py` line 16 (this is a temporary solution)
6. Run celery: `celery -A services.celery_push_notifications worker -Q push_notifications --loglevel=info -Ofair --hostname=%%h_notifications --concurrency=20 --pool=threads`
7. Run `python services/cron.py five_minutes`