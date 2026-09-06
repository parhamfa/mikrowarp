#!/usr/bin/env bash
# Runtime settings, also available in RouterOS container shells without image ENV.
set -Eeuo pipefail
readonly data_dir=/var/lib/mikrowarp
readonly run_dir=/run/mikrowarp
readonly tunnel=CloudflareWARP
readonly probe_ns=mikrowarp-probe
readonly probe_link=mwprobe
readonly probe_network=169.254.254.0/30
readonly probe_router=169.254.254.1
readonly probe_ip=169.254.254.2
readonly out_table=51887
readonly return_table=51888
if [[ -r "$run_dir/runtime.env" ]]; then source "$run_dir/runtime.env"; fi
uptime_s() { local value; read -r value _ </proc/uptime; printf '%s\n' "${value%%.*}"; }
log() { printf '[mikrowarp] %s\n' "$*"; }
cli() { timeout --kill-after=1 6 warp-cli --accept-tos "$@"; }
revoke() { nft flush set inet mikrowarp ready 2>/dev/null || true; }
publish() {
    local now state=$1 reason=$2
    now=$(uptime_s)
    printf 'state=%s\nreason=%s\nuptime=%s\nepoch=%s\n' "$state" "$reason" "$now" "$(date +%s)" > "$run_dir/status.new"
    mv "$run_dir/status.new" "$run_dir/status"
    if [[ ${last_status:-} != "$state:$reason" ]]; then log "$state: $reason"; last_status="$state:$reason"; fi
}
free_kib() { df -Pk "$data_dir" | awk 'NR==2 {print $4}'; }
