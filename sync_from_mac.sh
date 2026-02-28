#!/bin/bash
# Pull Mac data to the Pi.

MAC_LOCAL_HOST="Jareds-MacBook-Air.local"
MAC_LOCAL_IP="10.0.0.171"
MAC_TAILSCALE="100.106.101.57"
SSH_KEY="$HOME/.ssh/id_ed25519"
SRC="/Users/jaredgantt/pi-data/"
DEST="/home/jaredgantt/data/"

if [ ! -d "$DEST" ]; then
  mkdir -p "$DEST"
fi

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
  jaredgantt@"$HOST":"$SRC" \
  "$DEST"
