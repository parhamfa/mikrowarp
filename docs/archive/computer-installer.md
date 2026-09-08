> **Historical record.** New installations use the [two-command RouterOS installer](../usage.md). The commands below refer to the retired computer-side workflow preserved in the [v1 source history](https://github.com/parhamfa/mikrowarp/tree/v1.0.0/standard), not the current checkout. Current tests retain only the read helpers they need.

# MikroWARP Standard candidate

The r11-based gateway edition for **x86-64 CHR with IPv4 connectivity**. It retains
`warp-svc`, `warp-cli`, `warp-diag`, `warp-dex`, and r11's supporting Linux runtime.
The compact router edition is separate work. This candidate is not accepted for
general production use.

## What installation creates

| WinBox location | Objects | Purpose |
| --- | --- | --- |
| Container | `mikrowarp` | Official WARP client using MASQUE |
| Interfaces | `mikrowarp-link` bridge, `mikrowarp-veth`, one bridge port | Private transit link |
| IP → Addresses | One router-side /30 address | Reach the container's gateway address |
| IP → Firewall → NAT | One source NAT rule | Let the container establish its outer WARP connection |
| IP → Firewall → Filter | Three rules | Allow its uplink; block new connections from it to router services and other router interfaces |
| Container → Envs / Mounts | One environment entry and one mount list | Bind this installation to its persistent state |
| Files | One chosen directory | Image, registration, bounded output and recovery files |

Comments begin `MikroWARP | purpose` and end with the installation ID. The gateway
is named **mikrowarp**, without the redundant `-warp` suffix.

The installer creates **no client address lists, routing tables, routing rules,
mangle rules, Netwatch entries, System scripts or schedulers**. It does not edit
FastTrack, router DNS, global IPv6, or existing routing policies. Temporary admin
lease variables prevent concurrent installer operations and are removed on exit.

Admins decide which traffic reaches the gateway, local-network bypasses, FastTrack
exclusions, and whether to block or choose another uplink during an outage. The
container's outer connection follows the router's existing routing policy. The
profile's `wan` must name its actual outgoing interface. Avoid routing the
container's own source address back into itself.

Custom restrictive firewalls may also need an administrator's rule allowing
established return traffic and the chosen clients' traffic. The isolation rules
rely on connection tracking. They are not a substitute for RouterOS container
isolation or the administrator's overall firewall policy.

## Gateway health

The transit link and ARP remain available. **ICMP echo replies to the gateway
address are enabled only while a fresh health lease exists.** An administrator can
use `check-gateway=ping` on their own route; an always-running veth is no longer the
health signal.

Every normal check runs an internal Linux test client through the container's
forwarding and NAT path. Readiness requires:

- Official client reports connected and MASQUE configured.
- A Cloudflare trace confirms WARP egress.
- At least two of three non-Cloudflare HTTPS checks succeed.
- At least one of two UDP DNS resolvers answers through WARP.

Two successful checks open the gateway. A failed check closes it. A kernel timeout
expires readiness after 60 seconds without renewal, including when the controller
freezes. The independent supervisor restarts a stalled controller after roughly
two minutes, and RouterOS restarts an exited container. WAN outages are retried
without repeatedly replacing registration.

Packets received for forwarding can leave through WARP only. This protects traffic
that reaches the container. **RouterOS fallback is still the administrator's
choice:** a blackhole route discards matching traffic when the preferred route is
inactive; an alternative route can deliberately use another egress. Neither is
installed automatically. RouterOS's ping-check interval adds to detection time.

These checks establish sampled IPv4/UDP connectivity and the Linux forwarding
path. They cannot certify an admin's RouterOS policy, every Internet destination,
IPv6, or permanent Cloudflare availability. IPv6 forwarding is disabled inside
this edition; external IPv6 policy remains the admin's responsibility.

## Admin tool

Run the Python 3.11+/OpenSSH tool **from an admin computer**. It needs no resident
RouterOS management scripts. RouterOS 7.23.2 is the tested version; the current
installer admits 7.23.x and does not upgrade RouterOS, install packages, enable
device mode, format disks, or reboot a target. Container support must already be
enabled. See MikroTik's [container manual](https://manual.mikrotik.com/docs/containers/).

Copy `profile.example.json`, supply the explicit SSH endpoint, trusted known-hosts
file, expected router identity, uplink and storage directory. Generate the owner
value once using `python3 -c 'import uuid; print(uuid.uuid4().hex)'`. Keep the same
profile when resuming or updating. The owner value is an installation marker,
not a Cloudflare credential. Only use an unused RFC1918 /30 for the transit link.

From the repository root:

```sh
python3 standard/manage.py plan --profile my-router.json --bundle release/image.json
python3 standard/manage.py install --profile my-router.json --bundle release/image.json --archive release/image.tar.gz
python3 standard/manage.py status --profile my-router.json
python3 standard/manage.py update --profile my-router.json --bundle next-release/image.json --archive next-release/image.tar.gz
python3 standard/manage.py rollback --profile my-router.json
```

Use release metadata from a trusted source. The tool checks the local archive's
SHA-256, transfers it over authenticated SSH, checks its size and imported image
ID, and verifies the retained Cloudflare binaries. Bundle export independently
checks gzip integrity, image configuration and every layer hash. It does not
download the entire image back from the router for redundant transfer verification.

Installation can be rerun with the same profile and bundle. Updates stage the new
image before stopping WARP, then snapshot the stopped service's state. A failed
candidate restores the previous image and matching state. Successful operations
leave one container object; old root files are removed and a compressed previous
image is retained. A server-side lease prevents concurrent admin operations.

These operations manage an installation created by this Standard tool. They do
not adopt an existing pilot container or migrate its RouterOS routing policy.
Earlier unreleased RC1-RC3 lab images are not supported rollback targets; RC4 fixes
their missing runtime `sync` dependency.

For an interrupted admin operation, rerun `resume` or `abort`:

```sh
python3 standard/manage.py resume --profile my-router.json
python3 standard/manage.py abort --profile my-router.json
```

An interrupted cutover can leave the gateway deliberately in maintenance until
that command is run. This differs from normal reboot/WAN/service recovery, which
is automatic. An abruptly killed admin tool can leave a ten-minute lease to
expire. No automatic updater is installed.

## Disk and diagnostics

The runtime image is approximately **264.7 MB unpacked / 93.6 MB compressed**.
All four Cloudflare programs remain. This is the image size, not total operational
storage: the current compressed image is retained, and after an update so is one
previous compressed image. Two archives add approximately **187 MB**, plus a state
snapshot and current state. Staging needs additional temporary space; the tool
checks free space before proceeding. Reserve at least about 1.5 GB for installation
and update operations rather than sizing storage to the image alone.

The daemon's captured output uses two 1 MiB files. Known vendor log streams are
trimmed at 2 MiB during normal checks. Managed diagnostic ZIPs have a 32 MiB total
retention budget and expire after one day. Registration, settings, databases, and
unknown state files are not removed by log cleanup. Low free space stops WARP and
closes readiness rather than silently creating another registration. These are
managed-output limits and a free-space guard, not a hard quota on every filesystem
write or on administrator-created files.

For manual troubleshooting, open the container shell and run:

```sh
mikrowarp
warp-cli --accept-tos status
warp-diag --no-ansi --output /var/lib/mikrowarp/diagnostics
```

Diagnostic bundles and state snapshots may contain sensitive registration and
network information. Keep them private. An explicit diagnostic output directory
elsewhere is administrator-managed and outside automatic ZIP retention.

## Development and tests

`bundle.py --build --output NEW_DIRECTORY` checks the preserved r11 base ID, builds
the candidate, and exports an immutable bundle. It refuses to overwrite earlier
bundle evidence. The build-stage compiler and Python are not shipped.

The test harness in `lab.py` accepts only the two dedicated local QEMU VMs. The
generic admin tool is separate. `lab-bootstrap.rsc` and `lab-admin-policy.rsc` are
**lab fixtures**, not installer output. Disruptive testing must never target
an existing production router or its traffic.

See `RESULTS.md` for the final image identity, measured results, and acceptance
limits. A free CHR license caps transmit traffic at 1 Mbps per interface, so this
lab does not establish production throughput. [MikroTik CHR licensing](https://help.mikrotik.com/docs/spaces/ROS/pages/18350234/Cloud%20Hosted%20Router%20CHR)
