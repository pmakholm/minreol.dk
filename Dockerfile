# syntax=docker/dockerfile:1
FROM python:3.12-slim AS build
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN --mount=type=cache,sharing=locked,target=/var/cache/apt apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev python3-venv git

COPY . /neodb

RUN echo `cd /neodb && git rev-parse --short HEAD`-`cd /neodb/neodb-takahe && git rev-parse --short HEAD`-`date -u +%Y%m%d%H%M%S` > /neodb/build_version
RUN rm -rf /neodb/.git /neodb/neodb-takahe/.git

RUN mv /neodb/neodb-takahe /takahe

WORKDIR /neodb
RUN python -m venv /neodb-venv
RUN find misc/wheels-cache -type f | xargs -n 1 /neodb-venv/bin/python3 -m pip install || echo incompatible wheel ignored
RUN rm -rf misc/wheels-cache
RUN --mount=type=cache,sharing=locked,target=/root/.cache /neodb-venv/bin/python3 -m pip install --upgrade -r requirements.lock

WORKDIR /takahe
RUN python -m venv /takahe-venv
RUN --mount=type=cache,sharing=locked,target=/root/.cache /takahe-venv/bin/python3 -m pip install --upgrade -r requirements.lock

# runtime stage
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN --mount=type=cache,sharing=locked,target=/var/cache/apt-run apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev \
    busybox \
    nginx \
    gettext-base
RUN busybox --install

# postgresql and redis cli are not required, but install for development convenience
RUN --mount=type=cache,sharing=locked,target=/var/cache/apt-run apt-get install -y --no-install-recommends postgresql-client redis-tools gettext
RUN useradd -U app
RUN rm -rf /var/lib/apt/lists/*

COPY --from=build /neodb /neodb
WORKDIR /neodb
COPY --from=build /neodb-venv /neodb-venv
RUN /neodb-venv/bin/django-admin compilemessages
RUN NEODB_SECRET_KEY="t" NEODB_SITE_DOMAIN="x.y" NEODB_SITE_NAME="z" /neodb-venv/bin/python3 manage.py compilescss
RUN NEODB_SECRET_KEY="t" NEODB_SITE_DOMAIN="x.y" NEODB_SITE_NAME="z" /neodb-venv/bin/python3 manage.py collectstatic --noinput

COPY --from=build /takahe /takahe
WORKDIR /takahe
COPY --from=build /takahe-venv /takahe-venv
RUN TAKAHE_DATABASE_SERVER="postgres://x@y/z" TAKAHE_SECRET_KEY="t" TAKAHE_MAIN_DOMAIN="x.y" /takahe-venv/bin/python3 manage.py collectstatic --noinput

WORKDIR /neodb
COPY misc/bin/* /bin/
RUN mkdir -p /www

USER app:app

CMD [ "neodb-hello"]
