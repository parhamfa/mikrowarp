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

Tests use an explicit **lab administrator routing policy** to direct the test
client through WARP and activate a blackhole when gateway ping fails. The
installer itself creates none of those routes, tables or rules.

The last completed forwarding sample on 7.23.5 passed all four non-Cloudflare
HTTPS requests and both Cloudflare trace requests on their first attempt, plus
both UDP DNS resolvers. Earlier requests intermittently timed out, including
some while the internal health probes were passing. The harness retains up to
three attempts per HTTPS target; a pass demonstrates working connectivity,
not a zero-timeout service or a reliability percentage.

Development testing exposed delayed extracted-file writes after abrupt reboot
and delayed RouterOS cleanup of container directories. The installer now waits
for initial writes, rebuilds interrupted stopped candidates from their retained
archive, flushes update journals with the runtime helper and retries directory
cleanup. The affected interruption cases were rerun successfully.

The [earlier Standard runtime results](../RESULTS.md) remain separate. These
tests do not establish long-term uptime, production throughput, physical-router
support, ARM support, IPv6, or compatibility with future WARP image changes.
Private VM disks, router exports and registration material are not published.
