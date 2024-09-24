FROM nginx:alpine-slim

ARG PUBLIC_DOMAIN_NAME

COPY docker_management/nginx/prod.nginx.conf /etc/nginx/conf.d/default.conf

RUN apk update && \
    apk add perl && \
    mkdir -p /www/static && \
    in="my.domain" out="$PUBLIC_DOMAIN_NAME" perl -pi -e 's/\Q$ENV{"in"}/$ENV{"out"}/g' ./etc/nginx/conf.d/default.conf

WORKDIR /www
