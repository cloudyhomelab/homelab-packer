#!/bin/sh
# Fills every zone file the primary lacks. The secondary comes first: on a rebuilt primary it still
# holds the records OpenTofu added, which the baked files do not. Files bind already has are kept.
set -eu

SECONDARY=10.88.53.12
CONF=/etc/bind/zone-master.conf
BAKED=/seed

sed -n -e 's/^zone "\([^"]*\)".*/zone \1/p' -e 's/^[[:space:]]*file "\([^"]*\)".*/file \1/p' "$CONF" |
while read -r kind value; do
    if [ "$kind" = zone ]; then
        zone=$value
        continue
    fi
    file=$value
    [ -e "$file" ] && continue

    tmp="$file.seed"
    # dig exits 0 on a refused or failed transfer; the zone check is what rejects it
    if dig +nocmd +nostats +nocomments +onesoa +time=3 +tries=1 @"$SECONDARY" "$zone" AXFR > "$tmp" \
        && named-checkzone -q "$zone" "$tmp"; then
        echo "$zone: transferred from $SECONDARY"
    else
        cp "$BAKED/$zone.zone" "$tmp"
        echo "$zone: seeded from the baked file"
    fi
    chown 53:53 "$tmp"
    mv "$tmp" "$file"
done
