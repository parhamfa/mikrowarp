# MikroWARP

**A MikroTik CHR gateway powered by the official Cloudflare WARP client.**

MikroWARP runs Cloudflare's Linux client in a container and uses **MASQUE** for
the tunnel. The official client handles registration and connection management.
You decide which traffic to route through it.

```text
Your chosen clients → RouterOS routing → MikroWARP → WARP → Internet
```

**Current release: Standard r14 preview.** It supports **x86-64 CHR, IPv4 and
RouterOS 7.23+**; tested locally on **7.23.2 and 7.23.5**. Physical ARM
routers and a smaller Compact edition are future work.

[Download the preview](https://github.com/parhamfa/mikrowarp/releases/tag/r14-routeros-native)
· [Installation and management](standard/routeros/README.md)
· [Installer test results](standard/routeros/RESULTS.md)

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

The CHR needs **RouterOS 7.23 or newer**, the matching **container package**,
container device mode enabled, Internet access, and a correct clock for HTTPS.
The installer does not upgrade or reboot RouterOS.

Paste these two commands into the RouterOS terminal:

```routeros
/tool fetch url="https://raw.githubusercontent.com/parhamfa/mikrowarp/main/deploy/mikrotik/mikrowarp.rsc" dst-path=mikrowarp.rsc check-certificate=yes
/import mikrowarp.rsc
```

The router downloads the image, selects storage and an unused private `/30`,
creates the transit link, starts WARP, and checks forwarding. It prints your
**gateway address** when ready. No Python, SSH profile, generated ID, or
computer-side image download is needed.

Internal storage is preferred. If it is too small, the installer chooses the
writable mounted disk with the most free space. It remembers that location.
If multiple uplinks are possible, it stops with instructions for an explicit
[override](standard/routeros/README.md#optional-overrides).

Re-import the same file after a failed or interrupted operation. A completed
installation simply reports its status; it does not restart a healthy container.

**Your existing traffic stays on its current routes.** Send traffic to the new
gateway using your own routing policy. With the example subnet, its address is
`172.31.242.2`; the router-side address is `172.31.242.1`.

If WARP becomes unhealthy, the container stops forwarding client traffic and
stops answering gateway ping. Your RouterOS routes decide whether to use another
uplink or block traffic. See the [health and fallback explanation](standard/routeros/README.md#health-and-routing).

## Update and troubleshoot

To update, run the same two installation commands to fetch and import the newer
installer. Updates keep one previous image and its matching registration state.
A candidate that fails its connectivity check is rolled back automatically.

For status:

```routeros
:global mikrowarpAction "status"
/import mikrowarp.rsc
```

Use `"rollback"` to restore the previous accepted image and state, or `"abort"`
to cancel a saved unfinished operation. The action variable is consumed immediately.
If a reboot interrupts an update, **re-import to resume**; WARP may stay blocked
until you do. Ordinary Internet outages and service crashes recover automatically.

See the [native management guide](standard/routeros/README.md) for recovery,
storage, overrides and the exact WinBox footprint. The original
[computer-side bundle and guide](standard/GUIDE.md) remain available for existing
preview installations; the native installer does not adopt them automatically.

## Validation and development

The native installer was exercised on local CHRs running **7.23.2 and 7.23.5**:
storage selection, repeat imports, rejected downloads/images, update/rollback,
terminal disconnects and reboots during update phases. Forwarded non-Cloudflare
IPv4 and UDP DNS passed. Testing also found a packet-size feedback bug affecting
non-private client addresses; the installer now sets the transit MTU to 1300.
See the [installer acceptance record](standard/routeros/RESULTS.md).

The unchanged Standard r14 runtime's [earlier tests](standard/RESULTS.md) covered
startup, WAN loss, daemon/controller failure, DNS failure, Cloudflare-only
reachability and bounded storage. Its separate final observation passed 30/30
rounds. Health monitoring detects outages but cannot prevent them. Long-term
reliability, production throughput and varied upstream MTU paths remain unproved.

- [`standard/`](standard/) — current runtime, native installer sources and local test harnesses.
- [`standard/evidence/r14.json`](standard/evidence/r14.json) — sanitized measurements.
- [`build/README.md`](build/README.md) — building from the pinned reference image.
- [`container/`](container/) — source used to assemble the Ubuntu/glibc reference.

Private router profiles, registration, VM disks and host-specific experiments are
excluded from this repository. This is an independent project; Cloudflare and
MikroTik do not maintain or endorse it. See [third-party notices](NOTICE.md).
