#!/bin/sh
# Startar som root ENBART för att ge /data rätt ägare (så att Unraid-användare slipper chown),
# släpper sedan alla rättigheter och kör appen som PUID:PGID (standard 99:100 = nobody:users).
set -eu
PUID="${PUID:-99}"
PGID="${PGID:-100}"
DATA="${DATA_DIR:-/data}"

case "$PUID$PGID" in *[!0-9]*) echo "PUID/PGID måste vara siffror" >&2; exit 1;; esac
if [ "$PUID" = "0" ] || [ "$PGID" = "0" ]; then echo "Vägrar köra som root (PUID/PGID=0)" >&2; exit 1; fi

if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA"
  if [ "$(stat -c %u:%g "$DATA")" != "$PUID:$PGID" ]; then
    chmod 700 "$DATA" 2>/dev/null || true
    if ! chown "$PUID:$PGID" "$DATA"; then
      echo "Kunde inte ge $DATA ägaren $PUID:$PGID. Kör på servern: chown $PUID:$PGID <appdata-mappen>" >&2
      exit 1
    fi
    echo "Gav $DATA ägaren $PUID:$PGID"
  fi
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups --inh-caps=-all --no-new-privs -- "$@"
fi
exec "$@"
