#!/bin/sh
# The API's container starts here (ADR-0034): the database's migrations, then the server.
#
# Behind a platform's proxy, the server takes the client's address from X-Forwarded-For only
# from the addresses in FORWARDED_ALLOW_IPS (127.0.0.1 unless it is set), which the rate limits
# count by (ADR-0018). A platform that is the only way to the container sets it to *.
set -eu

alembic -c /app/apps/api/alembic.ini upgrade head
exec uvicorn sef_api.main:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}"
