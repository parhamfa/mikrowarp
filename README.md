# MikroWARP

**A MikroTik CHR gateway powered by the official Cloudflare WARP client.**

MikroWARP runs Cloudflare's Linux client in a container and uses **MASQUE** for
the tunnel. The official client handles registration and connection management.
You decide which traffic to route through it.

```text
Your chosen clients → RouterOS routing → MikroWARP → WARP → Internet
```

**Current release: Standard r14 preview.** It supports **x86-64 CHR, IPv4 and
RouterOS 7.23.x**; testing used 7.23.2. The installer rejects 7.21.x. Physical ARM
routers and a smaller Compact edition are future work.

[Download the preview](https://github.com/parhamfa/mikrowarp/releases/tag/r14-standard)
· [Installation guide](standard/GUIDE.md)
· [Test results](standard/RESULTS.md)

## What it does

- Provides a gateway IP that you can use in your own routes.
- Tests real forwarded HTTPS to multiple non-Cloudflare destinations and UDP DNS.
- Answers gateway ping only while WARP is healthy, so your route can use
  `check-gateway=ping`.
- Recovers from service crashes, router restarts and Internet interruptions.
- Keeps registration across restarts and supports manual update/rollback.
- Limits managed logs and diagnostic retention.

It installs **one container, a private transit link, one NAT rule and three
filter rules**. Comments start with `MikroWARP |`.

It creates **no client lists, mangle rules, routing tables, Netwatch entries,
System scripts or schedulers**. You own traffic selection, FastTrack exclusions,
local-network bypasses and WAN fallback. Monitoring runs inside the container.

## Size

| Item | Measured size |
| --- | ---: |
| Container image, unpacked | 264.7 MB |
| Image download | 93.6 MB |
| Container + two rollback archives + state in the lab | About 458 MB, plus filesystem overhead |
| Container RAM during a small paced load | 126–139 MB |

Allow roughly **1.5 GB of storage headroom** for installation and staged updates.
The installer checks available space. RAM figures describe the measured workload,
not a guaranteed maximum or minimum router specification. Standard retains all
four Cloudflare programs, including `warp-diag`.

## Install

Before starting, the CHR needs RouterOS **7.23.x**, the matching container package,
container device mode enabled, and working SSH key authentication. The tool runs
on your computer with **Python 3.11+ and OpenSSH**. It does not upgrade or reboot
the router. See the [prerequisites and profile details](standard/GUIDE.md#admin-tool).

1. Download **`mikrowarp-standard-r14-amd64.tar.gz`** from the
   [release page](https://github.com/parhamfa/mikrowarp/releases/tag/r14-standard).
   This contains the image and admin tool. `build-only-*` assets are for developers.

2. Extract the bundle and make your router profile:

   ```sh
   tar -xzf mikrowarp-standard-r14-amd64.tar.gz
   cd mikrowarp-standard-r14
   shasum -a 256 -c SHA256SUMS
   cp standard/profile.example.json my-router.json
   python3 -c 'import uuid; print(uuid.uuid4().hex)'
   ```

   Edit `my-router.json`: set your SSH address, port, key, trusted `known_hosts`
   file, expected router identity, uplink and storage directory. Choose an unused
   private `/30` subnet. Paste the generated value into `owner` and keep this
   profile for future updates.

3. Check the target, then install:

   ```sh
   python3 standard/manage.py plan --profile my-router.json --bundle image.json
   python3 standard/manage.py install --profile my-router.json --bundle image.json --archive image.tar.gz
   python3 standard/manage.py status --profile my-router.json
   ```

   `plan` checks prerequisites without changing the router. Once installation
   finishes, the tool prints the gateway address.

**Your existing traffic stays on its current routes.** Send traffic to the new
gateway using your own routing policy. With the example subnet, its address is
`172.31.242.2`; the router-side address is `172.31.242.1`.

If WARP becomes unhealthy, the container stops forwarding client traffic and
stops answering gateway ping. Your RouterOS routes decide whether to use another
uplink or block traffic. See the [health and fallback explanation](standard/GUIDE.md#gateway-health).

## Update and troubleshoot

Updates are explicit admin operations. The tool stages a candidate, saves state,
checks connectivity and restores the previous image/state if validation fails.
An interrupted admin cutover may need `resume` or `abort`.

The [admin guide](standard/GUIDE.md) covers update, rollback, diagnostic commands,
the exact WinBox footprint and storage retention.

## Validation and development

Local tests covered startup, WAN loss, daemon/controller failure, DNS failure,
Cloudflare-only reachability, storage pressure and update/rollback. The final
client observation passed **30/30 rounds**. Transient WARP timeouts also occurred
during earlier checks; health monitoring detects outages but cannot prevent them.
Long-term reliability, production throughput and varied MTU paths remain unproved.

- [`standard/`](standard/) — current runtime, admin tool and local test harnesses.
- [`standard/evidence/r14.json`](standard/evidence/r14.json) — sanitized measurements.
- [`build/README.md`](build/README.md) — building from the pinned reference image.
- [`container/`](container/) — source used to assemble the Ubuntu/glibc reference.

Private router profiles, registration, VM disks and host-specific experiments are
excluded from this repository. This is an independent project; Cloudflare and
MikroTik do not maintain or endorse it. See [third-party notices](NOTICE.md).
