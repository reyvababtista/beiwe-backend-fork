#!/bin/bash

#you may need to run this from inside the repository folder and/or change the directory setting under program:celery
# (looks like almost all logging happens in celeryd.err)

#literally just run this script and celery will work.
# tails the celery log, ctrl-c to exit the tail

# This looks like overkill, but resetting logs and permissions is super helpful
sudo mkdir -p /etc/supervisor/conf.d/

# Files need to have permissions 777 in order for the supervisor and celery
# processes to have full permissions to write regardless of the runtime user
# they occur under (supervisord may run as a root service, causing problems).
sudo mkdir -p /var/log/supervisor/
sudo chmod 777 /var/log/supervisor/
sudo chgrp adm /var/log/supervisor/
sudo rm -f /var/log/supervisor/supervisord.log
sudo touch /var/log/supervisor/supervisord.log
sudo chmod 777 /var/log/supervisor/supervisord.log
sudo chgrp adm /var/log/supervisor/supervisord.log

sudo mkdir -p /var/log/celery/
sudo chmod 777 /var/log/celery/
sudo chgrp adm /var/log/celery/

sudo rm -f /var/log/celery/celeryd_processing.log
sudo touch /var/log/celery/celeryd_processing.log
sudo chmod 777 /var/log/celery/celeryd_processing.log
sudo chgrp adm /var/log/celery/celeryd_processing.log
sudo rm -f /var/log/celery/celeryd_processing.err
sudo touch /var/log/celery/celeryd_processing.err
sudo chmod 777 /var/log/celery/celeryd_processing.err
sudo chgrp adm /var/log/celery/celeryd_processing.err

sudo rm -f /var/log/celery/celeryd_push_send.log
sudo touch /var/log/celery/celeryd_push_send.log
sudo chmod 777 /var/log/celery/celeryd_push_send.log
sudo chgrp adm /var/log/celery/celeryd_push_send.log
sudo rm -f /var/log/celery/celeryd_push_send.err
sudo touch /var/log/celery/celeryd_push_send.err
sudo chmod 777 /var/log/celery/celeryd_push_send.err
sudo chgrp adm /var/log/celery/celeryd_push_send.err

sudo tee /etc/supervisord.conf >/dev/null <<EOL
[supervisord]
logfile = /var/log/supervisor/supervisord.log
logfile_maxbytes = 10MB
logfile_backups=10
loglevel = info
pidfile = /tmp/supervisord.pid
nodaemon = false
minfds = 1024
minprocs = 200
umask = 022
identifier = supervisor
directory = /tmp
childlogdir = /tmp
strip_ansi = false

[inet_http_server]
port = 127.0.0.1:50001

[supervisorctl]
serverurl = http://127.0.0.1:50001

[program:celery_processing]
directory = /home/ubuntu/beiwe-backend/
command = python3 -m celery -A services.celery_data_processing worker --loglevel=info -Ofair --hostname=%%h_processing
stdout_logfile = /var/log/celery/celeryd_processing.log
stderr_logfile = /var/log/celery/celeryd_processing.err
autostart = true
#stopwaitsecs = 30
stopasgroup = true
startsecs = 5

[program:celery_push_send]
directory = /home/ubuntu/beiwe-backend/
command = python3 -m celery -A services.celery_push_notifications worker --loglevel=info -Ofair --hostname=%%h_notifications --concurrency=10
stdout_logfile = /var/log/celery/celeryd_push_send.log
stderr_logfile = /var/log/celery/celeryd_push_send.err
autostart = true
#stopwaitsecs = 30
stopasgroup = true
startsecs = 5
EOL

# start data processing
# supervisord

#echo "Use 'supervisord' or 'processing-start' to start the celery data processing service,"
#echo "use 'killall supervisord' or 'processing-stop' to stop it."
#echo "Note: you should not run supervisord as the superuser."

# uncomment when debugging:
#logc
