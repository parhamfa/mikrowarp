#!/usr/bin/env bash
set -Eeuo pipefail
fail() { printf '%s\n' "$1"; exit 1; }
# Drain CLI stdout: grep -q closes its pipe early and warp-cli can panic with
# exit 101 (broken pipe), which pipefail would misreport as an unhealthy tunnel.
timeout --kill-after=1 4 warp-cli --accept-tos status 2>/dev/null | grep -F 'Status update: Connected' >/dev/null || fail disconnected
timeout --kill-after=1 4 warp-cli --accept-tos settings 2>/dev/null | grep -F 'WARP tunnel protocol: MASQUE' >/dev/null || fail wrong_protocol
[[ $(cat /proc/sys/net/ipv4/ip_forward) == 1 ]] || fail forwarding_disabled
nft list chain inet mikrowarp forward >/dev/null 2>&1 || fail firewall_missing

scratch=$(mktemp -d /run/mikrowarp/probe.XXXXXX)
trap 'rm -rf "$scratch"' EXIT
read -r -a probes <<< "$WARP_PROBES"
((${#probes[@]} >= WARP_PROBE_QUORUM)) || fail invalid_quorum
pids=()
for i in "${!probes[@]}"; do
  (
    expected=${probes[$i]%%:*}
    url=${probes[$i]#*:}
    [[ "$expected" =~ ^2[0-9][0-9]$ && "$url" == https://* ]] || exit 1
    code=$(curl --noproxy '*' -4sS --connect-timeout 4 --max-time 8 \
      --proto '=https' --max-redirs 0 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null) || exit 1
    [[ "$code" == "$expected" ]] && touch "$scratch/$i.ok"
  ) & pids+=("$!")
done
(
  curl --noproxy '*' -4fsS --connect-timeout 4 --max-time 8 \
    https://cloudflare.com/cdn-cgi/trace 2>/dev/null | grep -E '^warp=(on|plus)$' >/dev/null && touch "$scratch/trace.ok"
) & pids+=("$!")
(
  dig -4 +notcp +time=3 +tries=1 +short @1.1.1.1 example.com A 2>/dev/null | \
    grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$' >/dev/null && touch "$scratch/dns.ok"
) & pids+=("$!")
for pid in "${pids[@]}"; do wait "$pid" || true; done
[[ -f "$scratch/trace.ok" ]] || fail warp_egress_failed
good=0
for i in "${!probes[@]}"; do [[ ! -f "$scratch/$i.ok" ]] || good=$((good + 1)); done
((good >= WARP_PROBE_QUORUM)) || fail "external_ipv4_${good}_of_${#probes[@]}"
[[ -f "$scratch/dns.ok" ]] || fail udp_dns_failed
printf 'external_ipv4_%s_of_%s\n' "$good" "${#probes[@]}"
