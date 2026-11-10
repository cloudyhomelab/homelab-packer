#!/bin/sh
# Resolves the IoT ingress proxy for Home Assistant's trusted_proxies, which accepts only
# addresses. Writes HA_TRUSTED_PROXY=<address> to the given env file, or to stdout without one.
set -eu

PROXY_NAME=iot-ctl.ip.cloudyhome.net

addr=$(getent ahostsv4 "$PROXY_NAME" | awk 'NR == 1 { print $1 }')
if [ -z "$addr" ]; then
    echo "cannot resolve $PROXY_NAME" >&2
    exit 1
fi

if [ $# -gt 0 ]; then
    echo "HA_TRUSTED_PROXY=$addr" > "$1"
else
    echo "HA_TRUSTED_PROXY=$addr"
fi
