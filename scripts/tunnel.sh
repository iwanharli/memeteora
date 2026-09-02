#!/bin/bash
# SSH tunnel to the VPS Postgres, so the local web app can read the same
# db_memet the VPS worker writes to.
#
#   scripts/tunnel.sh up      open it (idempotent)
#   scripts/tunnel.sh down    close it
#   scripts/tunnel.sh status  is it up?
#
# The tunnel exists because Postgres on the VPS listens for a handful of
# whitelisted IPs only, and a home IP is not stable enough to whitelist.
# Nothing in the firewall or pg_hba.conf has to change for this to work.
set -uo pipefail

HOST="${MEMET_VPS:-root@217.76.51.113}"
PORT="${MEMET_TUNNEL_PORT:-15432}"
MATCH="${PORT}:127.0.0.1:5432"

running() { pgrep -f "ssh .*-L ${MATCH} ${HOST}" >/dev/null 2>&1; }

case "${1:-up}" in
up)
    running && { echo "tunnel already up on ${PORT}"; exit 0; }
    # ExitOnForwardFailure so a busy port fails loudly instead of leaving a
    # live ssh with no forward; the keepalives drop it when the link dies,
    # which is what lets the idempotent check above stay honest.
    ssh -f -N -o BatchMode=yes -o ExitOnForwardFailure=yes \
        -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
        -L "${MATCH}" "${HOST}" || { echo "tunnel failed"; exit 1; }
    echo "tunnel up: localhost:${PORT} -> ${HOST} 5432"
    ;;
down)
    running || { echo "no tunnel on ${PORT}"; exit 0; }
    pkill -f "ssh .*-L ${MATCH} ${HOST}" && echo "tunnel closed"
    ;;
status)
    if running; then echo "up on ${PORT}"; else echo "down"; exit 1; fi
    ;;
*)
    echo "usage: $0 {up|down|status}" >&2; exit 2
    ;;
esac
