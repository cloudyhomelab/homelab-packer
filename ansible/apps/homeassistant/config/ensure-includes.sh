#!/bin/sh
# Creates the files configuration.yaml includes, as Home Assistant does only when it writes a
# default configuration.yaml itself; ours is mounted, so it never does. Existing files are kept.
# The owner is the container's root: the start of the app's range in /etc/subuid and /etc/subgid.
set -eu

APP=homeassistant
CONFIG_DIR=/srv/homeassistant/config

uid=$(awk -F: -v app="$APP" '$1 == app { print $2 }' /etc/subuid)
gid=$(awk -F: -v app="$APP" '$1 == app { print $2 }' /etc/subgid)
if [ -z "$uid" ] || [ -z "$gid" ]; then
    echo "no ID range for $APP in /etc/subuid or /etc/subgid" >&2
    exit 1
fi

create() {
    path="$CONFIG_DIR/$1"
    [ -e "$path" ] && return 0
    printf '%s' "$2" > "$path"
    chown "$uid:$gid" "$path"
    echo "created $path"
}

create automations.yaml '[]'
create scripts.yaml ''
create scenes.yaml ''
