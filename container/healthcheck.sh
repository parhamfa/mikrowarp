#!/usr/bin/env bash
set -Eeuo pipefail
file=/run/mikrowarp/status
[[ -r "$file" ]] || { echo 'starting'; exit 1; }
epoch=$(sed -n 's/^epoch=//p' "$file")
state=$(sed -n 's/^state=//p' "$file")
reason=$(sed -n 's/^reason=//p' "$file")
[[ "$epoch" =~ ^[0-9]+$ ]] || { echo 'invalid_status'; exit 1; }
age=$(( $(date +%s) - epoch ))
printf '%s %s age=%ss\n' "$state" "$reason" "$age"
[[ "$state" == ready && "$age" -ge 0 && "$age" -le 60 ]]
