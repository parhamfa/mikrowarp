#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

readonly state_dir=/run/mikrowarp
readonly tunnel=CloudflareWARP
warp_pid=''
last_state=''
failures=0
last_reconnect=0
restart_delay=5
needs_configure=true

log() { printf '[mikrowarp] %s\n' "$*"; }
publish() {
  local state=$1 reason=$2
  printf 'epoch=%s\nstate=%s\nreason=%s\nfailures=%s\n' \
    "$(date +%s)" "$state" "$reason" "$failures" > "$state_dir/status.new"
  mv "$state_dir/status.new" "$state_dir/status"
  if [[ "$state:$reason" != "$last_state" ]]; then
    log "state=$state reason=$reason"
    last_state="$state:$reason"
  fi
}
cleanup() {
  publish stopped shutdown
  if [[ -n "$warp_pid" ]] && kill -0 "$warp_pid" 2>/dev/null; then
    kill -TERM "$warp_pid" 2>/dev/null || true
    for _ in {1..20}; do
      kill -0 "$warp_pid" 2>/dev/null || break
      sleep 0.2
    done
    kill -KILL "$warp_pid" 2>/dev/null || true
    wait "$warp_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT
trap 'exit 0' TERM INT
cli() { timeout --kill-after=1 8 warp-cli --accept-tos "$@"; }
configure() {
  cli tunnel protocol set MASQUE >/dev/null 2>&1 &&
    cli mode warp >/dev/null 2>&1 && cli connect >/dev/null 2>&1
}

mkdir -p "$state_dir" /var/lib/cloudflare-warp /run/dbus
publish starting firewall
for variable in WARP_LIVENESS_INTERVAL WARP_FAILURE_THRESHOLD WARP_RECONNECT_INTERVAL WARP_PROBE_QUORUM; do
  [[ ${!variable} =~ ^[1-9][0-9]*$ ]] || { log "invalid $variable"; exit 1; }
done
uplink=${WARP_UPLINK_INTERFACE:-$(ip -4 route show table main default | awk '{for(i=1;i<=NF;i++) if($i=="dev") {print $(i+1);exit}}')}
[[ "$uplink" =~ ^[a-zA-Z0-9_.:-]{1,15}$ ]] || { log 'invalid uplink interface'; exit 1; }
read -r -a clients <<< "$WARP_CLIENT_SUBNETS"
((${#clients[@]})) || { log 'no client subnets configured'; exit 1; }
for subnet in "${clients[@]}" "$WARP_PROBE_SOURCE"; do
  [[ "$subnet" =~ ^[0-9.]+/[0-9]+$ ]] || { log 'invalid IPv4 subnet'; exit 1; }
done
client_set=$(IFS=,; printf '%s' "${clients[*]}")

# Install before starting WARP or enabling forwarding. Replace atomically.
nft list table inet mikrowarp >/dev/null 2>&1 && delete_table='delete table inet mikrowarp' || delete_table=''
nft -f - <<EOF
$delete_table
table inet mikrowarp {
  chain forward {
    type filter hook forward priority -10; policy drop;
    ct state invalid drop
    meta nfproto ipv4 iifname "$uplink" ip saddr { $client_set, $WARP_PROBE_SOURCE } oifname "$tunnel" counter accept
    meta nfproto ipv4 iifname "$tunnel" oifname "$uplink" ct state established,related counter accept
  }
  chain postrouting {
    type nat hook postrouting priority srcnat; policy accept;
    meta nfproto ipv4 oifname "$tunnel" counter masquerade
  }
  chain forward_mss {
    type filter hook forward priority mangle; policy accept;
    meta nfproto ipv4 oifname "$tunnel" tcp flags syn tcp option maxseg size set rt mtu
  }
}
EOF
if [[ $(cat /proc/sys/net/ipv4/ip_forward) != 1 ]]; then
  printf '1' > /proc/sys/net/ipv4/ip_forward
fi
# This prototype supports IPv4 forwarding only.
if [[ -w /proc/sys/net/ipv6/conf/all/forwarding ]]; then
  printf '0' > /proc/sys/net/ipv6/conf/all/forwarding
fi
if [[ ! -c /dev/net/tun ]]; then
  mkdir -p /dev/net
  mknod /dev/net/tun c 10 200
  chmod 0600 /dev/net/tun
fi
rm -f /run/dbus/pid
dbus-daemon --system --fork

while true; do
  if [[ -z "$warp_pid" ]] || ! kill -0 "$warp_pid" 2>/dev/null; then
    if [[ -n "$warp_pid" ]]; then
      wait "$warp_pid" 2>/dev/null || true
      publish recovering service_exited
      sleep "$restart_delay" & wait $! || true
      restart_delay=$((restart_delay * 2))
      (( restart_delay <= 60 )) || restart_delay=60
    fi
    warp-svc --accept-tos > /tmp/warp-svc.log 2>&1 &
    warp_pid=$!
    log 'service started'
    needs_configure=true
  fi

  if [[ "$needs_configure" == true ]] && cli status >/dev/null 2>&1; then
    publish connecting configuring
    if ! cli registration show >/dev/null 2>&1; then
      if [[ -s /var/lib/cloudflare-warp/reg.json ]]; then
        publish unready registration_unavailable
      else
        cli registration new >/dev/null 2>&1 || true
      fi
    fi
    if [[ -n "${WARP_LICENSE_KEY:-}" ]]; then
      cli registration license "$WARP_LICENSE_KEY" >/dev/null 2>&1 || true
    fi
    if configure; then needs_configure=false; fi
    last_reconnect=$(date +%s)
  fi

  if reason=$(/usr/local/sbin/warp-gateway-probe 2>/dev/null); then
    failures=0
    restart_delay=5
    publish ready "$reason"
  else
    failures=$((failures + 1))
    publish unready "${reason:-probe_failed}"
    now=$(date +%s)
    if (( failures >= WARP_FAILURE_THRESHOLD && now - last_reconnect >= WARP_RECONNECT_INTERVAL )); then
      cli disconnect >/dev/null 2>&1 || true
      configure || true
      last_reconnect=$now
      log 'requested reconnect after persistent failure'
    fi
  fi
  # Raw daemon logs can contain registration metadata. Keep them local and bounded.
  if [[ $(stat -c %s /tmp/warp-svc.log) -gt 2097152 ]]; then
    truncate -s 0 /tmp/warp-svc.log
  fi
  sleep "$WARP_LIVENESS_INTERVAL" & wait $! || true
done
