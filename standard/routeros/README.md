# Install and manage MikroWARP from RouterOS

This is the primary installation path for **Standard r14, x86-64 CHR, IPv4,
RouterOS 7.23+**. The router performs installation and management itself.
Physical routers, ARM and Compact remain separate work.
Tested locally on **7.23.2 and 7.23.5**; see [acceptance results](RESULTS.md).

## Install

First install the container package that matches your RouterOS version and
enable container device mode. Those are RouterOS prerequisites; MikroWARP does
not change device mode, install packages, upgrade RouterOS or reboot it.
The router must have Internet access and a correct clock for certificate checks.

```routeros
/tool fetch url="https://raw.githubusercontent.com/parhamfa/mikrowarp/main/deploy/mikrotik/mikrowarp.rsc" dst-path=mikrowarp.rsc check-certificate=yes
/import mikrowarp.rsc
```

Wait for **Ready. Gateway …** and **RESULT success**. Download and extraction
can take several minutes, including deliberate 45-second pauses while initial
records and extracted files are saved. The final check requires working WARP forwarding,
including non-Cloudflare HTTPS and UDP DNS. A running process alone is insufficient.

The installer chooses an unused private `/30`, generates its installation ID,
identifies the active main-table uplink and chooses storage. It prints the chosen
gateway; often this is `172.31.242.2`, but use the address it actually reports.

**Installing does not send any of your clients through WARP.** Add your own routes
and traffic policy after installation succeeds.

## What appears in WinBox

| Location | Installed objects |
| --- | --- |
| Container | One running container, `mikrowarp` |
| Interfaces | Bridge `mikrowarp-link`, veth `mikrowarp-veth`, one bridge port |
| IP → Addresses | One router-side address on the private transit `/30` |
| Firewall → NAT | One rule translating the container's own uplink traffic |
| Firewall → Filter | Three rules: protect router services, allow the container's uplink, block new container connections toward other networks |
| Container configuration | One state mount list and one installation-ID environment entry |
| Files | Installer, installation record, one latest operation log, and the chosen MikroWARP storage directory |

Comments have the form `MikroWARP | Transit link [installation-id]`. The ID lets
the installer distinguish its own objects from existing configuration. Occupied
names or conflicting objects cause a clear error; they are not silently adopted.
The three filter rules and NAT rule are placed before existing rules. Existing
rules keep their relative order.

The transit bridge uses **MTU 1300**, matching the pinned WARP tunnel. This lets
RouterOS return packet-size feedback to clients before large packets enter the
container, including clients with non-private source addresses. Re-importing a
newer installer corrects the MTU of an older owned transit bridge without
restarting the container. No extra mangle rule is needed.

There are **no installed System scripts, schedulers, Netwatch entries, client
address lists, mangle rules, policy routes or routing tables**. During an import,
an ordinary temporary script job and an operation lock exist. They are removed
after completion; an interrupted job's lock is reclaimed on the next import.

The previous container can coexist **stopped** during an update. Successful
completion returns to one container and retains the previous image as an archive.

## Status, update, rollback and abort

Status:

```routeros
:global mikrowarpAction "status"
/import mikrowarp.rsc
```

Update: run the same **fetch and import** commands from installation. The fetched
installer pins the release image. Importing the already-installed image reports
status without restarting it. Importing a different release stages that image,
pauses WARP, saves registration state, switches containers and validates forwarding.
Failed candidate validation restores the previous image and state automatically.

Restore the previous accepted image **and its matching saved state**:

```routeros
:global mikrowarpAction "rollback"
/import mikrowarp.rsc
```

Cancel an unfinished saved operation:

```routeros
:global mikrowarpAction "abort"
/import mikrowarp.rsc
```

Actions are consumed immediately. The following import defaults to normal
installation/resume behavior. Only one operation may run at a time. If another
import is still running, let it finish before issuing a new operation.

An aborted first installation keeps its owned files and registration, with its
container stopped. Re-import to retry. An aborted update restores the image and
state from before that attempt. Abort is not an uninstall command. After a commit
has begun, finish it by re-importing, then use rollback if wanted.

## Interrupted operations

Re-import the installer to resume after a terminal interruption, failed download
or reboot. Progress is stored on the router in two alternating journal files.
The script validates their checksums and ownership before using them, and uses
the existing runtime to flush update journals to disk before cutover.

An update interrupted during the switch can leave WARP blocked until re-import.
This is intentional: there is no persistent scheduler to finish administrator
operations. Ordinary Internet outages, WARP service crashes and normal runtime
reboots recover inside the container without re-importing.

After a terminal disconnect, the temporary background job may still finish.
A concurrent import reports that it is busy. Once the job has ended, re-import
either completes the saved operation or reports its current status.

Never delete the installation record, state directory or journals to fix a
failed update. The latest operation log explains the stopped phase. A missing
disk, conflicting object or corrupt ownership record is refused without adopting
or deleting unrelated configuration.

## Storage and downloads

Standard r14 is **93,635,286 bytes compressed** and about **264.7 MB unpacked**.
It retains `warp-svc`, `warp-cli`, `warp-diag` and `warp-dex` unchanged.

For staging, the installer budgets the archive plus twice the unpacked image
and a 256 MiB reserve: **891,453,966 free bytes** for this image. Existing retained
files also occupy space; this is an additional free-space check, not the total
size of an installed system. About 1.5 GB of storage headroom is a useful starting
point. A retained archive reduces the additional requirement by its download
size; the extraction reserve is still checked. Extraction and filesystem overhead vary.

Internal storage is preferred if sufficient. Otherwise, it selects the writable
mounted disk with the most free space. Saved installations keep their chosen
location; re-import does not move state to another disk.

The actual container image is the release asset
[`mikrowarp-standard-r14-linux-amd64.tar.gz`](https://github.com/parhamfa/mikrowarp/releases/download/r14-standard/mikrowarp-standard-r14-linux-amd64.tar.gz).
It is separate from the older computer-side bundle. Downloads use
certificate-checked HTTPS and a temporary filename. The byte count must match
before import; the extracted image ID must match before it can start. The installer
also verifies the four vendor binary hashes and real forwarding.
See the [RouterOS Fetch reference](https://manual.mikrotik.com/docs/cli-reference/tool/fetch/)
for the certificate and redirect options.

RouterOS does not provide the archive SHA-256 operation used by our build tools.
The native installer therefore does **not** claim to cryptographically hash the
whole archive before extraction. The published SHA-256 file remains available
for independent verification; native checks are TLS, exact length, pinned image
ID, vendor binaries and forwarding.

Completed updates keep one current archive, one previous archive, and the matching
previous state snapshot. Older managed snapshots and archives are removed. Runtime
logs and diagnostic retention remain bounded by the Standard container.

## Optional overrides

Most routers need none. If the main routing table has multiple active uplinks,
choose the interface explicitly before the first import:

```routeros
:global mikrowarpOptions {"uplink"="ether1"}
/import mikrowarp.rsc
```

All three choices can be supplied together:

```routeros
:global mikrowarpOptions {"uplink"="ether1";"network"="172.31.242.0/30";"directory"="pcie1/mikrowarp"}
/import mikrowarp.rsc
```

Use your real interface and mounted disk names. The subnet must be an unused,
aligned RFC1918 `/30`. The directory must be unused and contain only letters,
digits, underscores, hyphens and path separators. Overrides are consumed once.
After installation, conflicting overrides are refused; relocation is not an update.

## Health and routing

You choose client traffic, local bypasses, FastTrack exclusions and fallback.
The container forwards IPv4 through WARP only while its forwarding checks pass.
It answers gateway ping only while that health result remains fresh. ARP and the
local transit link remain present when WARP is unhealthy.

Your route can use the reported gateway with `check-gateway=ping`. When probes
fail or expire, ping and forwarding stop; RouterOS then applies **your** routing
policy. Use an alternative route if you want fallback, or an appropriate blackhole
or `lookup-only-in-table` policy if you want traffic blocked. Health detection
does not prevent Cloudflare or the underlying Internet from having outages.

## Developer files

`bootstrap.rsc`, `worker.rsc`, `operations.rsc` and `main.rsc` are the source.
`build.py` renders the single published `deploy/mikrotik/mikrowarp.rsc` file.
The image itself remains the verified Standard r14 image.

```sh
python3 standard/routeros/build.py
python3 standard/routeros/build.py --check
```

`labctl.py`, `acceptance.py`, `preflight-tests.py` and `public-install-test.py`
are disposable-QEMU test tools. They do not install
anything on a real router and are not used by end users. Acceptance evidence is
published separately from private VM disks, exports and WARP registration data.
