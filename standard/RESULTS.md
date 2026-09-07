# Standard r14 candidate validation

> Later [native-installer testing](routeros/RESULTS.md) found a packet-size
> feedback issue for non-private client addresses that this earlier sample
> missed. The native installer now sets transit MTU 1300. The results below
> describe the earlier test conditions, not proof against that edge case.

The Standard edition keeps the r11 runtime and all four original Cloudflare
programs. It adds the gateway-only installer, internal forwarding checks,
expiring ping readiness, service supervision, bounded managed output, and explicit
update/rollback. All execution in this work used disposable local Docker/QEMU
resources. Existing production routers and their traffic were untouched during
this validation work.

## Final image

| Measurement | Result |
| --- | ---: |
| Unpacked logical image | 264,691,612 bytes (264.69 MB / 252.43 MiB) |
| Compressed import archive | 93,635,286 bytes (93.64 MB / 89.30 MiB) |
| Added over preserved r11 | 35,062 bytes |
| RouterOS-reported container size | 264,692,388 bytes |
| `warp-svc` | 93,675,944 bytes |
| `warp-cli` | 15,663,368 bytes |
| `warp-diag` | 32,981,040 bytes |
| `warp-dex` | 29,665,496 bytes |

Image ID:
`sha256:f54570f4b9ede63f337640053a4daccf5da70d0cdfe04f2330ecebaf26a93f39`

Archive SHA-256:
`abb7dd5220e38d146185455b7427c019337d0e83e983bf0e37929febd3193da1`

Cloudflare binary hashes match r11. Export validation checked gzip integrity,
image configuration, blob hashes and all layer diff IDs. The build checks that
the base contains no WARP registration; runtime source hashes match the final
image's embedded manifest. Compiler and Python build dependencies are absent
from the final runtime.

Total router storage is larger than the image: approximately 358 MB plus state
after initial installation, and 452 MB plus state/snapshot after retaining a
previous release. Staging needs temporary extra space. The admin guide explains
the conservative free-space check and roughly 1.5 GB operating headroom.

The final router inventory contained one container, two archives totalling
187,271,034 bytes, and a 6,377,245-byte persistent directory including its one
recovery snapshot. Combined with RouterOS's container-size reading, this is
**458,340,667 bytes of logical payload**, before filesystem allocation/metadata
overhead. There were no abandoned uploads or temporary admin variables. Container
size is a RouterOS [reported property](https://manual.mikrotik.com/docs/cli-reference/container/),
not a physical disk-allocation measurement.

## Runtime and router checks

The final RC4 image passed all six native fault cases:

- Forwarded external HTTPS and health-aware gateway ping.
- Cloudflare reachable while other IPv4 connections are blocked: readiness and
  client forwarding close even though the official client says connected.
- Both forwarded UDP DNS resolvers blocked: readiness closes.
- One DNS resolver unavailable: the surviving resolver keeps the gateway usable.
- Frozen controller: kernel lease expires, ping and forwarding stop, ARP remains,
  and the independent supervisor restarts the container. Recovery took 154.6 s.
- Killed `warp-svc`: the service recovers with the original registration.

The actual QEMU CHR run used RouterOS 7.23.2 and passed seven cases on RC1:

- Fresh installation left ordinary client traffic outside WARP and created no
  traffic-selection or RouterOS monitoring objects. Exactly three owned filter
  rules and one owned NAT rule were present.
- Separately installed admin routing sent both an RFC1918 client and a
  `198.18.14.10` benchmark-address client through WARP; GitHub HTTPS and UDP DNS
  worked. The benchmark address is not evidence for every public-address setup.
- Frozen controller made the admin's actual `check-gateway=ping` route inactive
  and its chosen blackhole active; recovery was automatic in 165.5 s.
- Service crash preserved registration and recovered forwarding.
- WAN loss/restoration recovered automatically (66.3 s including the outage).
- Normal router reboot recovered automatically (63.8 s).
- Abrupt VM reset with WAN disconnected, followed by WAN restoration, recovered
  without shell intervention (105.4 s including the offline interval).

RC4 retains RC1's forwarding, probe and supervision design. The later changes
make stale status report unready, pause storage cleanup during maintenance, and
replace a missing rollback `sync` command with the bundled filesystem-sync helper.
Final-image reboot, lifecycle and client observations are recorded below;
earlier RC1 results are not relabelled as RC4 tests.

## Storage and diagnostics

All five storage cases passed again on RC4: a 32 MiB output stream retained two
1 MiB files; a full log filesystem drained output without hanging; a log symlink
did not overwrite another file; known logs and diagnostic ZIPs were pruned while
registration and unknown state survived; and a 32 MiB state filesystem held the
daemon before registration rather than starting without adequate free space.

The unchanged `warp-diag` produced a valid 271,291-byte ZIP with 98 entries on RC3.
Every ZIP entry passed CRC verification. The private diagnostic contents are not
part of the distributed image or evidence summary.

## Lifecycle and final observation

All five lifecycle cases passed on the real QEMU CHR:

| Case | Observed outcome |
| --- | --- |
| Repeat the same installation | Same router object IDs, no container restart, registration retained |
| Preflight and concurrency | Wrong owner and overlapping subnet rejected; simulated insufficient space rejected; a second live admin operation denied |
| Interrupt update after the saved-state checkpoint | Maintenance persisted; explicit `resume` completed the update and preserved registration |
| Roll back a working update | Previous image restored; a deliberately changed file returned to its matching saved-state value |
| Candidate that exits with code 42 | Automatically rejected; original image, registration and state restored; failed archive removed |

The update/rollback comparison used a lab sibling with identical RC4 runtime files
and a different image label. The bad candidate changed only its entrypoint to
exit immediately. Successful and recovered operations left exactly one container
object. The interruption was a controlled administrator-tool interruption at a
persisted checkpoint, not a complete matrix of arbitrary power-loss instants.

The final RC4 reboot restored readiness and its registration automatically in
68.4 seconds. Two concurrent 2 MiB downloads from a non-Cloudflare Hetzner endpoint
completed with HTTP 206 and exact byte counts in 63.0 and 63.5 seconds, each paced
at 32 KiB/s. Sixteen RouterOS samples over 80 seconds measured container memory
between **125.8 and 139.1 MB**, averaging **128.3 MB**. These are cgroup memory
observations in this limited load, not a memory ceiling or minimum router-RAM claim.

The final client observation passed **30/30 complete rounds over 274.4 seconds**:
fixed-address GitHub HTTPS 200, Google HTTPS 204, Cloudflare `warp=on`, UDP DNS and
fresh gateway readiness. No failed samples were retried or discarded. The final
observation ended at **2026-09-06 20:38:22 UTC** (September 7 in Tehran).

## Scope and limitations

The tests found and corrected real integration faults: RouterOS denied the mount
step in `ip netns exec`, so a small network-namespace helper replaces it; pinned
Cloudflare policy routing needed an explicit transit mark and return route;
repeating `/container set` could restart a running container, so idempotent
installation avoids those writes; and stripped r11 lacks `sync`, so rollback
uses the bundled fsync helper. A failed RC3 rollback required a lab-only recovery
shim. RC1-RC3 remain private development evidence, not supported rollback targets.

This is a locally validated candidate, not general production acceptance. The
installer targets x86-64 CHR on RouterOS 7.23.x; 7.23.2 is the tested version. It
does not upgrade a router. IPv6 forwarding and physical ARM routers are outside
this edition's current acceptance. Days of uptime, representative production
throughput and varied MTU/ISP paths remain unproved.

The free CHR lab has a 1 Mbps transmit cap per interface; paced downloads do not
establish maximum throughput or minimum router RAM. The connection can still
experience Cloudflare/underlay outages. During one RC4 installer check, the
official client reported connected while forwarded TLS/trace requests timed out;
DNS still answered. Readiness stayed closed and connectivity recovered without
manual intervention. That observation does not establish the outage's cause.

Health sampling cannot certify every destination or an administrator's routing
policy. Container forwarding uses WARP only; whether RouterOS uses another WAN
after a route withdraws remains the administrator's decision. Output retention
is not a hard quota over all files. Interrupted admin cutovers can require
`resume` or `abort`; routine WAN, daemon and boot recovery are automatic.

Raw lab profiles, registrations, snapshots, packet evidence and diagnostics stay
under the private `runtime/standard-r14` directory. Only sanitized measurements
and the empty-state image belong in the release bundle.

The named native test containers and both dedicated QEMU VMs are stopped after
validation. Their private state and the immutable reports are retained. Other
Docker projects and production hosts are outside this cleanup.
