#!/bin/sh
set -e

if [ ! -f "${UGB_CONFIG:-/app/config.yaml}" ]; then
    echo "FATAL: config not found at ${UGB_CONFIG:-/app/config.yaml}"
    echo "Mount it as a volume: ./config.yaml:/app/config.yaml:ro"
    exit 1
fi

exec python -m app.main "$@"
