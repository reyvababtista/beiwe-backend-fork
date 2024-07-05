FROM postgres

ARG DOMAIN_NAME

RUN cp /cert/live/$DOMAIN_NAME/fullchain.pem /var/lib/postgresql/data/server.crt
RUN cp /cert/live/$DOMAIN_NAME/privkey.pem /var/lib/postgresql/data/server.key

RUN chown postgres:postgres /var/lib/postgresql/data/server.crt /var/lib/postgresql/data/server.key
RUN chmod 600 /var/lib/postgresql/data/server.key