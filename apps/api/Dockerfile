# The API's image (ADR-0034): the FastAPI application with its validator, the rule sets fetched
# by their pins and compiled while the image is built, and the database's migrations applied
# each time a container starts. From the repository's root:
#
#   docker build -f apps/api/Dockerfile -t sef-kopilot-api .
#   docker run -p 8000:8000 -e DATABASE_URL=... -e SEF_JWT_SECRET=... sef-kopilot-api
#
# The base images are arguments so that a build without access to their registries can name
# mirrors of them; the defaults are the official images.
ARG PYTHON_IMAGE=python:3.12-slim
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.7

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# The dependencies first, from the lock file alone, so that a change of the code keeps them.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/README.md apps/api/
COPY packages/einvoice_core/pyproject.toml packages/einvoice_core/README.md packages/einvoice_core/
RUN uv sync --frozen --no-dev --package sef-kopilot-api --no-install-workspace

# Then the code. The workspace's packages are installed from where they are, so that the API
# finds the rule sets and the corpus beside them, as it does in the repository.
COPY packages/einvoice_core packages/einvoice_core
COPY apps/api apps/api
RUN uv sync --frozen --no-dev --package sef-kopilot-api

# The rule sets, checked against their pins: those the build was given are kept if they pass
# the check, and fetched from their official sources otherwise. Every profile's stylesheets are
# then compiled here, once, rather than when a container starts.
COPY scripts/fetch_rulesets.py scripts/
COPY third_party third_party
RUN python scripts/fetch_rulesets.py --check || python scripts/fetch_rulesets.py
ENV EINVOICE_RULESETS_DIR=/app/third_party
RUN ["/app/.venv/bin/python", "-c", "from sef_api.invoices.validation import warm_up; problem = warm_up(); assert problem is None, problem"]

# The official documents the explanations cite, for `python -m sef_api.rag.ingest`.
COPY corpus corpus

FROM ${PYTHON_IMAGE}
# A user of its own, which owns nothing: the code, the rule sets and their compiled stylesheets
# are root's, and readable.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin sef
WORKDIR /app
COPY --from=build /app /app
ENV PATH=/app/.venv/bin:$PATH \
    EINVOICE_RULESETS_DIR=/app/third_party \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SEF_ENVIRONMENT=production \
    PORT=8000
USER sef
EXPOSE 8000
# Liveness, as /health answers it: the process is up. Readiness, /ready, is the platform's.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['PORT'] + '/health', timeout=4)"]
CMD ["/app/apps/api/docker/start.sh"]
