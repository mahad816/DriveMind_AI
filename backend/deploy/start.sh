#!/bin/sh
set -eu
# No migrations, collection provisioning or activation in this entrypoint.
# Access logs are disabled: OAuth callback URLs carry code/state secrets.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --workers 1 --no-access-log --no-proxy-headers --timeout-graceful-shutdown 150
