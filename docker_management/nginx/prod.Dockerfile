FROM nginx:alpine-slim

ARG PUBLIC_DOMAIN_NAME

COPY docker_management/nginx/prod.nginx.conf /etc/nginx/conf.d/default.conf

RUN mkdir -p /www/static && \
    sed -i 's/my.domain/$PUBLIC_DOMAIN_NAME/g' /etc/nginx/conf.d/default.conf

WORKDIR /www
