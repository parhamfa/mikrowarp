# MikroWARP

Run Cloudflare's official WARP client on MikroTik RouterOS in one container.
MikroWARP uses MASQUE to provide an IPv4 gateway with connection monitoring,
automatic service recovery and persistent WARP registration. Installation and
management run directly on the router.

## Install

Requires **x86-64 CHR with RouterOS 7.23+**, the matching container package,
container device mode enabled, working Internet access and a correct router clock.
Check the [storage requirements](docs/usage.md#storage-and-downloads) before
installing. The installer chooses a free transit subnet and storage location;
routers with multiple active uplinks may need an
[explicit uplink choice](docs/usage.md#optional-overrides).

Paste these two commands into the RouterOS terminal:

```routeros
/tool fetch url="https://github.com/parhamfa/mikrowarp/releases/latest/download/mikrowarp.rsc" dst-path=mikrowarp.rsc check-certificate=yes http-max-redirect-count=5
/import mikrowarp.rsc
```

Wait for **Ready. Gateway …** and note the gateway address. Download, extraction
and connectivity checks can take several minutes. Installation does not
automatically route your clients through WARP.

## What gets installed

- One running `mikrowarp` container with persistent registration and state.
- A dedicated bridge, veth and private `/30` transit network.
- One NAT rule for the container's uplink and three filter rules for uplink
  access and isolation from router services and other networks.
- Managed installation records, bounded logs, and image/state files for updates
  and rollback.

Rules and interfaces have comments such as `MikroWARP | Transit link [installation-id]`.
Monitoring runs inside the container; no permanent RouterOS scripts, schedulers
or Netwatch entries are installed.

## Using the gateway

Use the printed gateway address in your own routes. You manage traffic selection,
local bypasses, FastTrack exclusions and fallback policy.

The container checks non-Cloudflare IPv4 HTTPS and UDP DNS connectivity. When
marked unhealthy, it blocks forwarding and stops answering gateway pings.
Routes can use `check-gateway=ping` to respond to this signal; your routing policy
determines whether traffic falls back to another connection or remains blocked.
Normal Internet outages and service crashes recover automatically.

## Updates and management

Run the same two installation commands to update to the latest release.
Re-importing the installed release reports status without restarting it.
Updates retain the previous image and its matching registration state for rollback.

Re-import after an interrupted installation or update to resume. An update
interrupted during the switch may leave WARP blocked until you do so.
See the [management commands](docs/usage.md#status-update-rollback-and-abort)
for status, rollback and abort, and the [operation guide](docs/usage.md) for
troubleshooting.

## Project scope

MikroWARP provides the official WARP client, IPv4 forwarding, monitoring and
recovery on supported CHRs. Packaging, forwarding, monitoring and recovery
defects are project issues.

Destination reachability also depends on Cloudflare, your uplink and the remote
service. Passing health checks does not guarantee every application works.
MikroWARP does not select an exit country or provide destination-specific relays.
Support currently covers x86-64 CHR and IPv4.

[Documentation](docs/README.md) · [Research and validation](docs/archive/README.md) · [Third-party notices](NOTICE.md)
