#!/bin/bash
# Push Pi data to the Mac.

MAC_LOCAL_HOST="Jareds-MacBook-Air.local"
MAC_LOCAL_IP="10.0.0.171"
MAC_TAILSCALE="100.106.101.57"
SSH_KEY="$HOME/.ssh/id_ed25519"
SRC="/home/jaredgantt/data/"
DEST="/Users/jaredgantt/pi-data/"
LOCK="/tmp/pisync_pi_to_mac.lock"
DEBOUNCE=20

if [ ! -d "$SRC" ]; then
  exit 0
fi

now=$(date +%s)
if [ -f "$LOCK" ]; then
  last=$(stat -c %Y "$LOCK" 2>/dev/null || echo 0)
  if [ $((now - last)) -lt $DEBOUNCE ]; then
    exit 0
  fi
fi
/usr/bin/touch "$LOCK"

if ssh -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=no -i "$SSH_KEY" jaredgantt@"$MAC_LOCAL_HOST" true 2>/dev/null; then
  HOST="$MAC_LOCAL_HOST"
elif ssh -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=no -i "$SSH_KEY" jaredgantt@"$MAC_LOCAL_IP" true 2>/dev/null; then
  HOST="$MAC_LOCAL_IP"
elif ssh -o ConnectTimeout=5 -o BatchMode=yes -o StrictHostKeyChecking=no -i "$SSH_KEY" jaredgantt@"$MAC_TAILSCALE" true 2>/dev/null; then
  HOST="$MAC_TAILSCALE"
else
  exit 0
fi

rsync -az --delete \
  -e "ssh -i $SSH_KEY -o BatchMode=yes -o StrictHostKeyChecking=no" \
  "$SRC" \
  jaredgantt@"$HOST":"$DEST"
