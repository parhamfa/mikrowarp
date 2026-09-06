#!/usr/bin/env bash
set -Eeuo pipefail
source /usr/local/lib/mikrowarp/common.sh
# Runs in the dedicated network namespace, through the gateway FORWARD/NAT path.
[[ $(ip -4 route show default) == *"via $probe_router"* ]] || { echo probe_route_missing; exit 1; }
scratch="$run_dir/probe-current"
mkdir -p "$scratch"
rm -f "$scratch"/*.ok "$scratch"/*.result
pids=()
resolve() {
    local address
    for resolver in 1.1.1.1 9.9.9.9; do
        address=$(dig -4 -b "$probe_ip" +notcp +time=2 +tries=1 +short @"$resolver" "$1" A 2>/dev/null |
            grep -E '^([0-9]{1,3}\.){3}[0-9]{1,3}$' | awk 'NR==1 {print}')
        [[ -z "$address" ]] || { printf '%s\n' "$address"; return 0; }
    done
    return 1
}
urls=(
  '204:https://www.gstatic.com/generate_204'
  '200:https://en.wikipedia.org/robots.txt'
  '200:https://github.com/robots.txt'
)
for i in "${!urls[@]}"; do
    (
        target=${urls[$i]#*:}; expected=${urls[$i]%%:*}
        host=${target#https://}; host=${host%%/*}; address=$(resolve "$host") || exit 1
        result=$(curl --noproxy '*' --interface eth0 -4sS --connect-timeout 4 --max-time 8 \
            --resolve "$host:443:$address" \
            --proto '=https' --max-redirs 0 -o /dev/null -w '%{http_code} %{remote_ip} %{time_total}' "$target" 2>/dev/null) || {
            printf 'failed\n' > "$scratch/https-$i.result"; exit 1;
        }
        printf '%s\n' "$result" > "$scratch/https-$i.result"
        [[ ${result%% *} == "$expected" ]] && touch "$scratch/https-$i.ok"
    ) & pids+=("$!")
done
(
    address=$(resolve cloudflare.com) || exit 1
    curl --noproxy '*' --interface eth0 -4fsS --connect-timeout 4 --max-time 8 \
        --resolve "cloudflare.com:443:$address" \
        --proto '=https' --max-redirs 0 https://cloudflare.com/cdn-cgi/trace 2>/dev/null | \
        grep -E '^warp=(on|plus)$' > "$scratch/trace.result" && touch "$scratch/trace.ok"
) & pids+=("$!")
for resolver in 1.1.1.1 9.9.9.9; do
    (
        dig -4 -b "$probe_ip" +notcp +time=3 +tries=1 +short @"$resolver" example.com A 2>/dev/null | \
            grep -E '^([0-9]{1,3}\.){3}[0-9]{1,3}$' > "$scratch/dns-$resolver.result" && touch "$scratch/dns-$resolver.ok"
    ) & pids+=("$!")
done
for pid in "${pids[@]}"; do wait "$pid" || true; done
[[ -f "$scratch/trace.ok" ]] || { echo warp_trace_failed; exit 1; }
good=0
for i in "${!urls[@]}"; do [[ ! -f "$scratch/https-$i.ok" ]] || good=$((good+1)); done
(( good >= 2 )) || { echo "external_ipv4_${good}_of_3"; exit 1; }
dns_good=0
for resolver in 1.1.1.1 9.9.9.9; do
    [[ ! -f "$scratch/dns-$resolver.ok" ]] || dns_good=$((dns_good+1))
done
(( dns_good >= 1 )) || { echo udp_dns_0_of_2; exit 1; }
printf 'forwarded_ipv4_%s_of_3_dns_%s_of_2\n' "$good" "$dns_good"
