#!/usr/bin/env bash
# Only known disposable output is trimmed. Registration and settings are untouched.
set -Eeuo pipefail
source /usr/local/lib/mikrowarp/common.sh
mkdir -p "$data_dir/logs" "$data_dir/diagnostics"
# Vendor log streams may live beside registration. Touch only this explicit list.
for name in daemon.log daemon.1.log daemon.2.log daemon.3.log daemon_dns.log dns_stats.log \
    connection_stats.log boringtun.log dex.log captive-portal.log \
    cfwarp_daemon_dns.txt cfwarp_route_change_log.txt cfwarp_service_boring.txt \
    cfwarp_service_captive_portal.txt cfwarp_service_connection_stats.txt cfwarp_service_dex.txt \
    cfwarp_service_dns_stats.txt cfwarp_service_dynamic_log.txt cfwarp_service_log.txt \
    cfwarp_service_network_health_stats.txt cfwarp_service_taskdump.txt cfwarp_snapshots_collection.txt; do
    file="$data_dir/state/$name"
    if [[ -f "$file" && ! -L "$file" ]] && (( $(stat -c %s "$file") > 2097152 )); then
        truncate -s 0 "$file"
    fi
done
# Managed diagnostics expire after one day; oversized bundles are disposable.
find "$data_dir/diagnostics" -maxdepth 1 -type f -name 'warp-debugging-info-*.zip' \
    \( -mtime +0 -o -size +32M \) -delete
# Leave recent normal files alone, but bound the total known ZIP inventory to 32 MiB.
total=0
while IFS= read -r -d '' entry; do
    file=${entry#* }
    size=$(stat -c %s "$file"); total=$((total+size))
    if (( total > 33554432 )); then rm -f -- "$file"; fi
done < <(find "$data_dir/diagnostics" -maxdepth 1 -type f -name 'warp-debugging-info-*.zip' -printf '%T@ %p\0' | sort -z -nr)
