#!/usr/bin/env bash
set -Eeuo pipefail
source /usr/local/lib/mikrowarp/common.sh
if [[ "${1:-}" == maintenance ]]; then
    shift; exec /usr/local/lib/mikrowarp/maintenance.sh "$@"
fi
[[ -r "$run_dir/status" ]] || { echo 'state=starting'; exit 1; }
record=$(cat "$run_dir/status")
then=$(sed -n 's/^uptime=//p' <<<"$record")
[[ "$then" =~ ^[0-9]+$ ]] || exit 1
age=$(( $(uptime_s)-then ))
[[ ${uplink:-} ]] || exit 1
lease=false
nft get element inet mikrowarp ready "{ \"$uplink\" }" >/dev/null 2>&1 && lease=true
effective=false
if [[ "$lease" == true && "$age" -ge 0 && "$age" -le "${lease_seconds:-60}" ]] && grep -qx 'state=ready' <<<"$record"; then effective=true; fi
if [[ "$effective" != true ]] && grep -qx 'state=ready' <<<"$record"; then
    printf 'state=unready\nreason=health_lease_expired\n'
else
    printf '%s\n' "$record"
fi
printf 'age_seconds=%s\n' "$age"
printf 'health_lease=%s\n' "$lease"
[[ "$effective" == true ]]
