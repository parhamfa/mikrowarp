#!/usr/bin/env bash
set -Eeuo pipefail

# RouterOS 7.21.5 container namespaces put the local table at priority 200.
# WARP installs its catch-all at 199, which then captures its own 127.0.2.x DNS
# sockets. Restore standard Linux local delivery inside this namespace before
# starting WARP. No host routing or Cloudflare binary is changed.
rules=$(ip -4 rule show)
if ! grep -Eq '^0:[[:space:]]+from all lookup local$' <<< "$rules"; then
  if grep -Eq '^0:' <<< "$rules"; then
    printf '[mikrowarp-pilot] unexpected priority-zero rule; refusing startup\n' >&2
    exit 1
  fi
  ip -4 rule add priority 0 lookup local
fi
ip -4 route get 127.0.2.2 | grep -Eq '^local .*dev lo' || {
  printf '[mikrowarp-pilot] local DNS route is not loopback; refusing startup\n' >&2
  exit 1
}
exec /usr/local/sbin/warp-gateway
