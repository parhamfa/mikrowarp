#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
ulimit -c 0
source /usr/local/lib/mikrowarp/common.sh
# Close readiness before mount validation or slower network setup can fail.
nft list table inet mikrowarp_boot >/dev/null 2>&1 || nft -f - <<'EOF'
table inet mikrowarp_boot {
    chain input { type filter hook input priority -20; policy accept; icmp type echo-request drop; }
    chain forward { type filter hook forward priority -20; policy drop; }
}
EOF
warp_pid=''; logger_pid=''; last_status=''; successes=0; failures=0; last_reconnect=0; restart_delay=5
state_id=${MIKROWARP_STATE_ID:-}
interval=${MIKROWARP_INTERVAL:-10}
lease_seconds=${MIKROWARP_LEASE_SECONDS:-60}
min_free_mib=${MIKROWARP_MIN_FREE_MIB:-64}
for value in "$interval" "$lease_seconds" "$min_free_mib"; do [[ "$value" =~ ^[0-9]+$ ]] || exit 2; done
(( interval >= 5 && interval <= 30 && lease_seconds >= 45 && lease_seconds <= 120 && min_free_mib >= 8 )) || exit 2
mkdir -p "$run_dir"
stop_service() {
    if [[ -n "$warp_pid" ]] && kill -0 "$warp_pid" 2>/dev/null; then
        kill -TERM "$warp_pid" 2>/dev/null || true
        for _ in {1..30}; do kill -0 "$warp_pid" 2>/dev/null || break; sleep 0.2; done
        kill -KILL "$warp_pid" 2>/dev/null || true
        wait "$warp_pid" 2>/dev/null || true
    fi
    warp_pid=''
}
cleanup() { revoke; stop_service; publish stopped shutdown; }
trap cleanup EXIT
trap 'exit 0' TERM INT
[[ "$state_id" =~ ^[a-f0-9]{32}$ ]] || { publish error state_id_missing; exit 2; }
grep -Fq ' /var/lib/mikrowarp ' /proc/self/mountinfo || { publish error persistent_mount_missing; exit 2; }
[[ -f "$data_dir/owner.txt" && ! -L "$data_dir/owner.txt" && $(cat "$data_dir/owner.txt") == "$state_id" ]] || {
    publish error persistent_state_mismatch; exit 2;
}
mkdir -p "$data_dir/state" "$data_dir/logs" "$data_dir/diagnostics" /run/dbus /dev/net
[[ -c /dev/net/tun ]] || { mknod /dev/net/tun c 10 200; chmod 0600 /dev/net/tun; }
uplink=${MIKROWARP_UPLINK:-$(ip -4 route show table main default | awk '{for(i=1;i<=NF;i++)if($i=="dev"){print $(i+1);exit}}')}
router_ip=$(ip -4 route show table main default dev "$uplink" | awk '{for(i=1;i<=NF;i++)if($i=="via"){print $(i+1);exit}}')
gateway_ip=$(ip -4 -o addr show dev "$uplink" scope global | awk 'NR==1 {split($4,a,"/");print a[1]}')
[[ "$uplink" =~ ^[A-Za-z0-9_.:-]{1,15}$ && "$router_ip" =~ ^[0-9.]+$ && "$gateway_ip" =~ ^[0-9.]+$ ]] || {
    publish error uplink_configuration_missing; exit 2;
}
for var in uplink router_ip gateway_ip interval lease_seconds min_free_mib state_id; do
    printf '%s=%q\n' "$var" "${!var}"
done > "$run_dir/runtime.env"

# Restore local delivery before Cloudflare's priority-199 rule.
rules=$(ip -4 rule show)
if ! grep -Eq '^0:[[:space:]]+from all lookup local$' <<<"$rules"; then
    ! grep -Eq '^0:' <<<"$rules" || { publish error local_rule_conflict; exit 2; }
    ip -4 rule add priority 0 lookup local
fi
ip -4 route get 127.0.2.2 | grep -Eq '^local .*dev lo' || { publish error local_delivery_failed; exit 2; }

# A small internal client exercises actual forwarding and NAT without RouterOS rules.
ip netns delete "$probe_ns" 2>/dev/null || true
ip link delete "$probe_link" 2>/dev/null || true
ip netns add "$probe_ns"
ip link add "$probe_link" type veth peer name eth0 netns "$probe_ns"
ip addr add "$probe_router/30" dev "$probe_link"
ip link set "$probe_link" up
/usr/local/libexec/mikrowarp-io netns ip link set lo up
/usr/local/libexec/mikrowarp-io netns ip addr add "$probe_ip/30" dev eth0
/usr/local/libexec/mikrowarp-io netns ip link set eth0 up
/usr/local/libexec/mikrowarp-io netns ip route add default via "$probe_router"

# These rules are entirely inside the container, ahead of vendor policy routing.
rule() { local pref=$1; shift; ip -4 rule show | grep -q "^$pref:" && { publish error internal_rule_conflict; exit 2; }; ip -4 rule add priority "$pref" "$@"; }
rule 10 iif "$uplink" lookup "$out_table"
rule 11 iif "$probe_link" lookup "$out_table"
rule 12 iif "$tunnel" lookup "$return_table"
ip -4 route add blackhole default metric 32760 table "$out_table"
ip -4 route add blackhole default metric 32760 table "$return_table"
ip -4 route add "$probe_network" dev "$probe_link" table "$return_table"
ip -4 route add default via "$router_ip" dev "$uplink" onlink metric 10 table "$return_table"
delete=''
nft list table inet mikrowarp >/dev/null 2>&1 && delete='delete table inet mikrowarp'
nft -f - <<EOF
$delete
table inet mikrowarp {
    set ready { type ifname; flags timeout; timeout ${lease_seconds}s; }
    chain prerouting {
        type filter hook prerouting priority mangle; policy accept;
        # This pinned WARP version exempts mark 0x100cf from its own routing
        # table. Route transit packets with our explicit forward/return tables,
        # including replies to public client addresses and vendor bypass ranges.
        meta nfproto ipv4 iifname { "$uplink", "$probe_link", "$tunnel" } meta mark set 0x100cf
    }
    chain input {
        type filter hook input priority -10; policy accept;
        iifname @ready ip daddr $gateway_ip icmp type echo-request counter accept
        iifname "$uplink" ip daddr $gateway_ip icmp type echo-request counter drop
    }
    chain forward {
        type filter hook forward priority -10; policy drop;
        ct state invalid counter drop
        meta nfproto ipv4 iifname "$probe_link" ip saddr $probe_ip oifname "$tunnel" counter accept
        meta nfproto ipv4 iifname "$tunnel" oifname "$probe_link" ip daddr $probe_ip ct state established,related counter accept
        meta nfproto ipv4 iifname @ready oifname "$tunnel" counter accept
        meta nfproto ipv4 iifname "$tunnel" oifname @ready ct state established,related counter accept
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
nft delete table inet mikrowarp_boot
printf 1 > /proc/sys/net/ipv4/ip_forward
for setting in /proc/sys/net/ipv6/conf/all/forwarding; do [[ ! -w "$setting" ]] || printf 0 > "$setting"; done
for setting in /proc/sys/net/ipv6/conf/{all,default}/disable_ipv6; do [[ ! -w "$setting" ]] || printf 1 > "$setting"; done
rm -f /run/dbus/pid
dbus-daemon --system --fork
configure() { cli tunnel protocol set MASQUE >/dev/null 2>&1 && cli mode warp >/dev/null 2>&1 && cli connect >/dev/null 2>&1; }
needs_configure=true
publish starting connecting
while true; do
    if [[ -f "$data_dir/maintenance.lock" ]]; then
        revoke; stop_service; successes=0; publish maintenance administrator_operation
        sleep 2 & wait $! || true
        continue
    fi
    /usr/local/lib/mikrowarp/storage.sh || log 'managed log cleanup failed'
    if (( $(free_kib) < min_free_mib * 1024 )); then
        revoke; stop_service; successes=0; publish unready storage_low
        sleep "$interval" & wait $! || true
        continue
    fi
    if [[ -z "$warp_pid" ]] || ! kill -0 "$warp_pid" 2>/dev/null; then
        revoke; successes=0
        if [[ -n "$warp_pid" ]]; then
            wait "$warp_pid" 2>/dev/null || true
            publish recovering service_exited
            sleep "$restart_delay" & wait $! || true
            restart_delay=$((restart_delay*2)); (( restart_delay <= 60 )) || restart_delay=60
        fi
        warp-svc --accept-tos > >(/usr/local/libexec/mikrowarp-io log "$data_dir/logs" 1048576) 2>&1 &
        warp_pid=$!
        printf '%s\n' "$warp_pid" > "$run_dir/warp.pid"
        needs_configure=true
    fi
    if [[ "$needs_configure" == true ]] && cli status >/dev/null 2>&1; then
        if ! cli registration show >/dev/null 2>&1; then
            if [[ -s "$data_dir/state/reg.json" ]]; then
                publish unready registration_unavailable
            else
                cli registration new >/dev/null 2>&1 || true
            fi
        fi
        if configure; then needs_configure=false; fi
        last_reconnect=$(uptime_s)
    fi
    if ip link show "$tunnel" >/dev/null 2>&1; then
        ip -4 route replace default dev "$tunnel" metric 10 table "$out_table" || true
    fi
    reason=disconnected
    if cli status 2>/dev/null | grep -F 'Status update: Connected' >/dev/null && \
        cli settings 2>/dev/null | grep -F 'WARP tunnel protocol: MASQUE' >/dev/null && \
        reason=$(timeout --kill-after=2 20 /usr/local/libexec/mikrowarp-io netns /usr/local/lib/mikrowarp/probe.sh 2>/dev/null); then
        successes=$((successes+1)); failures=0; restart_delay=5
        if (( successes >= 2 )); then
            nft -f - <<EOF
flush set inet mikrowarp ready
add element inet mikrowarp ready { "$uplink" timeout ${lease_seconds}s }
EOF
            publish ready "$reason"
        else
            publish recovering first_good_check
        fi
    else
        revoke; successes=0; failures=$((failures+1)); publish unready "${reason:-probe_timeout}"
        now=$(uptime_s)
        if (( failures >= 3 && now-last_reconnect >= 120 )); then
            cli disconnect >/dev/null 2>&1 || true
            configure || true
            last_reconnect=$now
        fi
    fi
    sleep "$interval" & wait $! || true
done
