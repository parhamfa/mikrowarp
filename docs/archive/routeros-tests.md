# Native RouterOS installer acceptance

Tests performed on **7 September 2026**, using disposable local x86 CHR VMs.
RouterOS **7.23.2 (stable)** used internal storage; **7.23.5 (long-term)** used
a mounted ext4 disk because its small internal disk was insufficient.
No production router was used for these tests.

The runtime is the existing **Standard r14** image, unchanged:

```text
Image ID: f54570f4b9ede63f337640053a4daccf5da70d0cdfe04f2330ecebaf26a93f39
Archive:  93,635,286 bytes
SHA-256:  abb7dd5220e38d146185455b7427c019337d0e83e983bf0e37929febd3193da1
```

All four Cloudflare programs remain present and match the runtime's pinned
binary hashes. Update tests use a private sibling image with the same runtime
and a different image identity, plus a deliberately broken startup candidate.
They test the installer state machine; they do not certify an unreleased WARP version.

| Test | Observed result |
| --- | --- |
| Exact public two-command install on both versions | Router fetched the published installer and image itself; all four vendor hashes and forwarding passed; unrelated configuration unchanged; no temporary objects remained |
| Initial install on 7.23.2 | Router downloaded the actual release image over certificate-checked HTTPS; selected internal storage; forwarding healthy |
| Initial install on 7.23.5 | Selected the writable external disk; skipped an occupied transit `/30`; forwarding healthy |
| Repeat import and status | No healthy-process restart or journal rewrite; action variable consumed |
| Insufficient storage, occupied names/path/subnet, malformed subnet, ambiguous uplinks | Refused; unrelated exported configuration unchanged |
| WAN cut during image download | Partial download removed; re-import reused the saved installation and completed |
| Short download and unexpected image ID | Rejected; previous installation stayed healthy; abort removed staged objects |
| Deliberately broken candidate | Automatically restored the previous image and registration |
| Update and explicit rollback | Accepted image switched; rollback restored the matching saved registration |
| Concurrent import | Second import refused while the first operation was active |
| Terminal disconnect | Temporary background job completed; next import reclaimed its stale lock |
| Abrupt reboot in staging, quiescing, switching, validating and committing | Re-import completed the saved update with registration preserved |
| Cached image with insufficient extraction space | Refused before cutover; previous image and registration preserved |
| Interrupted shell-result files | Re-import removed reserved temporary files without restarting WARP |
| Forwarded IPv4 from private and non-private test addresses | GitHub and Google HTTPS succeeded; Cloudflare trace reported `warp=on` |
| Forwarded UDP DNS | Successful queries through WARP to 1.1.1.1 and 9.9.9.9 |
| Normal reboot and killed WARP service | Automatic recovery; registration preserved |
| Boot without WAN, then restore WAN | Gateway unavailable while offline; automatic recovery without import |
| Cloudflare reachable, other IPv4 blocked | Official client remained connected; monitor withdrew gateway ping and blocked forwarding; recovered after fault removal |
| Probe UDP DNS blocked | Monitor withdrew gateway ping and blocked forwarding; recovered after fault removal |
| Frozen controller | Kernel readiness lease expired while ARP remained; supervisor recovered automatically in about 165 seconds |
| Cold non-private-source packet-size regression | At transit MTU 1500 the TLS handshake stalled; at MTU 1300 RouterOS delivered size feedback and four Google IPv4 destinations succeeded on their first request |
| Correcting an older native transit bridge | Re-import set MTU 1300 with process IDs and registration unchanged |
| Larger forwarded download on both versions | Non-private client downloaded a 1 MiB range from the GitHub release asset; HTTP 206, exact byte count and SHA-256 matched |
| Existing client before adding lab policy | Cloudflare trace reported `warp=off`; after the explicit lab policy it reported `warp=on` |

Tests use an explicit **lab administrator routing policy** to direct the test
client through WARP and activate a blackhole when gateway ping fails. The
installer itself creates none of those routes, tables or rules.

An early 7.23.5 forwarding sample passed all four non-Cloudflare HTTPS requests
and both Cloudflare trace requests on their first attempt. Later tests exposed
a repeatable failure that this sample had missed: a first connection from the
non-private source could finish TCP setup but stall on a large TLS ClientHello.
A previous private-source request could populate the client's destination MTU
cache and hide the failure. Internal health probes also stayed green.

Packet capture showed large segments retransmitting without packet-size feedback.
Setting the **transit bridge MTU to 1300** moved that feedback to RouterOS, where
it reached the client. The negative control at MTU 1500 timed out again; after
re-import corrected the bridge, all four tested Google IPv4 addresses succeeded
on their first request and capture confirmed an ICMP message advertising MTU
1300. The image, vendor binaries, process IDs and registration were unchanged.
The forwarding harness now clears cached MTU information, starts with the
non-private source and tests UDP DNS from both sources.

With the final published installer, both versions passed all four HTTPS checks
and both WARP trace checks on their first attempt, DNS from both source addresses,
and the verified 1 MiB transfer. Both recovered automatically from a subsequent
router reboot; the 7.23.5 run also repeated WARP service-crash recovery. The exact
two-command installations took about six minutes in these emulated VMs.

Some earlier timeouts remain unclassified; they should not all be attributed
to Cloudflare. The harness retains up to three attempts per HTTPS target. Passing
these bounded checks is not a zero-timeout guarantee or a reliability percentage.

Development testing exposed delayed extracted-file writes after abrupt reboot
and delayed RouterOS cleanup of container directories. The installer now waits
for initial writes, rebuilds interrupted stopped candidates from their retained
archive, flushes update journals with the runtime helper and retries directory
cleanup. The affected interruption cases were rerun successfully.

The [earlier Standard runtime results](runtime-tests.md) remain separate. These
tests do not establish long-term uptime, production throughput, physical-router
support, ARM support, IPv6, or compatibility with future WARP image changes.
Private VM disks, router exports and registration material are not published.
The [sanitized evidence](evidence/routeros-native.json) records the passing
cases and their limits without registration or router credentials.
