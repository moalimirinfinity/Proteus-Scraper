#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -eq 0 ]; then
  echo "Usage: wait_for_services.sh host:port [host:port...]" >&2
  exit 1
fi

for target in "$@"; do
  host="${target%:*}"
  port="${target#*:}"
  echo "Waiting for ${host}:${port}..."
  until (echo >"/dev/tcp/${host}/${port}") >/dev/null 2>&1; do
    sleep 1
  done
  echo "${host}:${port} is available."
done
