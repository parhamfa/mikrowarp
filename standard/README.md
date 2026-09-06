# MikroWARP Standard

The r11-based, x86-64 gateway candidate. See [the admin guide](GUIDE.md)
for installation, footprint, health behavior, storage costs and recovery.

## Product boundary

- One container named `mikrowarp`, a private veth/transit link, persistent state,
  and only the container's necessary uplink/isolation configuration.
- Admins own routing tables, traffic selection, mangle, bypasses, FastTrack and
  the choice between blocking and another gateway during an outage.
- The gateway accepts routed IPv4 without a client-subnet allowlist. Its own
  forwarding firewall permits WARP egress and established return traffic only.
- Gateway ICMP echo replies represent fresh WARP health. A kernel timeout must
  revoke both readiness and forwarding if the controller freezes. The link and
  ARP remain available while the tunnel recovers.
- All four Cloudflare headless binaries from the verified r11 image remain.
- Health checks, service recovery and bounded log maintenance live inside the
  container. Installation/update/rollback are explicit admin operations.
- This edition is IPv4-only. Admins own any IPv6 bypass/failover policy outside
  the container. Container health cannot certify an admin's routing policy.

## Implementation and validation

1. Build and inventory the r11-derived runtime; verify retained vendor hashes.
2. Verify routed return paths, WARP-only forwarding and expiring ping readiness.
3. Make installation resumable and check conflicts/free space before mutations.
4. Stage updates separately, preserve matching state, and exercise rollback.
5. Bound managed logs/diagnostics and guard registration against cleanup.
6. Exercise forwarding, startup, WAN loss, daemon/controller failure, reboot,
   power loss, interrupted update and storage pressure.
7. Publish exact image measurements, tested versions and remaining limits.

Every disruptive test runs on dedicated local QEMU VMs. No test in this directory
may target a production router, an SSH alias, or a non-loopback endpoint. Its lab access
code enforces that boundary. The generic admin installer is separate from the
lab's guarded execution harness. Read [RESULTS.md](RESULTS.md) for measured
outcomes and the limits of this candidate.
