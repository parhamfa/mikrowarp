#!/usr/bin/env bash
# Explicit, local-only admin operations; no network API or periodic updater.
set -Eeuo pipefail
umask 077
source /usr/local/lib/mikrowarp/common.sh
sync_path() { /usr/local/libexec/mikrowarp-io sync "$@"; }
held() {
    [[ -f "$data_dir/maintenance.lock" ]] && grep -qx 'state=maintenance' "$run_dir/status" &&
    ! pgrep -x warp-svc >/dev/null
}
case "${1:-}" in
    begin)
        printf 'administrator_operation\n' > "$data_dir/maintenance.lock.new"
        sync_path "$data_dir/maintenance.lock.new"
        mv "$data_dir/maintenance.lock.new" "$data_dir/maintenance.lock"; sync_path "$data_dir"
        for _ in {1..40}; do held && { echo maintenance_ready; exit 0; }; sleep 1; done
        echo maintenance_pending; exit 1
        ;;
    resume)
        rm -f "$data_dir/restored.txt" "$data_dir/maintenance.lock"; sync_path "$data_dir"; echo resume_requested
        ;;
    snapshot)
        held || { echo service_must_be_in_maintenance; exit 2; }
        label=${2:-}; [[ "$label" =~ ^[0-9a-f]{64}$ ]] || exit 2
        mkdir -p "$data_dir/recovery"
        target="$data_dir/recovery/$label.tar"
        if [[ -e "$target" ]]; then
            if [[ ! -e "$target.sha256" ]]; then
                tar -tf "$target" >/dev/null
                sha256sum "$target" > "$target.sha256"; sync_path "$target.sha256" "$data_dir/recovery"
            fi
            sha256sum -c "$target.sha256"; exit 0
        fi
        size=$(du -sk "$data_dir/state" | awk '{print $1}')
        (( $(free_kib) > size+65536 )) || { echo insufficient_snapshot_space; exit 3; }
        tar --numeric-owner -C "$data_dir" -cf "$target.partial" state
        tar -tf "$target.partial" >/dev/null
        sync_path "$target.partial"
        mv "$target.partial" "$target"
        sha256sum "$target" > "$target.sha256.new"
        sync_path "$target.sha256.new"
        mv "$target.sha256.new" "$target.sha256"; sync_path "$data_dir/recovery"
        echo snapshot_ready
        ;;
    restore)
        held || { echo service_must_be_in_maintenance; exit 2; }
        label=${2:-}; [[ "$label" =~ ^[0-9a-f]{64}$ ]] || exit 2
        target="$data_dir/recovery/$label.tar"
        sha256sum -c "$target.sha256" >/dev/null
        # Recover an interrupted directory swap before doing any new extraction.
        if [[ ! -d "$data_dir/state" && -d "$data_dir/state.previous" ]]; then
            mv "$data_dir/state.previous" "$data_dir/state"
        fi
        if [[ -f "$data_dir/restored.txt" && $(cat "$data_dir/restored.txt") == "$label" ]]; then
            echo state_already_restored; exit 0
        fi
        rm -rf -- "$data_dir/restore.partial"
        mkdir "$data_dir/restore.partial"
        tar --no-same-owner -xf "$target" -C "$data_dir/restore.partial"
        [[ -d "$data_dir/restore.partial/state" && ! -L "$data_dir/restore.partial/state" ]]
        # Complete the backup on disk before making it the active registration.
        find "$data_dir/restore.partial" -type f -exec /usr/local/libexec/mikrowarp-io sync {} +
        find "$data_dir/restore.partial" -depth -type d -exec /usr/local/libexec/mikrowarp-io sync {} +
        rm -rf -- "$data_dir/state.previous"
        mv "$data_dir/state" "$data_dir/state.previous"; sync_path "$data_dir"
        mv "$data_dir/restore.partial/state" "$data_dir/state"; sync_path "$data_dir"
        printf '%s\n' "$label" > "$data_dir/restored.txt.new"; sync_path "$data_dir/restored.txt.new"
        mv "$data_dir/restored.txt.new" "$data_dir/restored.txt"; sync_path "$data_dir"
        rm -rf -- "$data_dir/state.previous" "$data_dir/restore.partial"
        echo state_restored
        ;;
    *) echo 'Usage: mikrowarp maintenance begin|resume|snapshot IMAGE_SHA256|restore IMAGE_SHA256'; exit 2 ;;
esac
