# WARP carrier experiments: NAT64 and Psiphon

**Recorded September 8, 2026. Decision: conclude the research and keep both
workarounds out of the Standard image and installer.**

MikroWARP's purpose is to provide the official WARP client on MikroTik, with
working forwarding, monitoring and recovery. Adding public relays to compensate
for individual upstream paths would introduce more dependencies and failure
modes. These results preserve the investigation; they are not supported
installation instructions or a promise of a future feature.

## Question and method

Some Telegram endpoints repeatedly failed through one WARP path while other
Telegram endpoints, browsing and DNS worked. Could changing how the official
client reaches Cloudflare restore those connections while retaining WARP as the
final Internet exit?

The disposable lab CHR and production pilot both ran RouterOS 7.23.5 with the
[published Standard r14 image](runtime-tests.md#final-image):

`sha256:f54570f4b9ede63f337640053a4daccf5da70d0cdfe04f2330ecebaf26a93f39`

Only the lab's WARP transport was changed. A temporary restricted relay let the
lab compare its own WAN with the pilot's WAN. The production WARP instance was
not restarted or reconfigured, and production clients were not moved onto the
experimental paths. The lab kept its WARP process, registration and Cloudflare
endpoint unchanged across the comparisons.

The successful alternatives used a temporary TCP adapter and MASQUE over
HTTP/2. The adapter carried WARP's encrypted connection without terminating it:

```text
Forwarded IPv4 client → official WARP client
                            │
                      encrypted WARP connection
                            │
              ordinary WAN / NAT64 / Psiphon
                            │
                      Cloudflare → Telegram
```

Each completed set comprised 36 unauthenticated MTProto exchanges: three affected
Telegram addresses and one working control, each on TCP ports 443, 80 and 5222,
repeated three times. The probe sent `req_pq_multi` and validated `resPQ` with its
matching random nonce. Each round required a fresh Cloudflare `warp=on` trace.
No account login, credentials or message content was involved. The lab client's
routes prevented direct-WAN fallback.

## Observed results

| Carrier for the lab WARP connection | Reported Cloudflare colo | Affected paths | Control paths |
| --- | --- | ---: | ---: |
| Original pilot WAN, before | IST | 0/27 | 9/9 |
| NAT64 over pilot IPv6 | FRA | 27/27 | 9/9 |
| NAT64 over lab IPv6 | ZRH | 27/27 | 9/9 |
| Psiphon Germany over pilot WAN | FRA | 27/27 | 9/9 |
| Psiphon Germany over lab WAN | FRA | 27/27 | 9/9 |
| Psiphon over pilot WAN, after interruption and recovery | FRA | 27/27 | 9/9 |
| NAT64 over pilot IPv6, after interruption and recovery | AMS | 27/27 | 9/9 |
| Original pilot WAN, restored | IST | 0/27 | 9/9 |

IST, FRA, ZRH and AMS denote Istanbul, Frankfurt, Zurich and Amsterdam. These are
observed Cloudflare trace values, not selectable or guaranteed exit locations.

Across the completed sets, each alternative passed **81/81 affected checks and
27/27 controls**. The original path failed **54/54 affected checks** across the
before/after runs while passing **18/18 controls**. This supports a path-dependent
failure; it does not isolate the responsible network component or establish a
general Telegram, UDP or MTProto restriction.

Google and Wikipedia HTTPS and UDP DNS to Cloudflare and Quad9 passed in every
completed carrier set. Independent IP checks returned Cloudflare exit addresses.
Some GitHub API responses were HTTP 403 with an exhausted shared-IP rate-limit
message; those were completed connections, not timeouts.

## What each alternative changed

**NAT64** used the public [level66.services translator](https://level66.services/services/nat64/)
with prefix `2001:67c:2960:6464::/96`. An IPv6 carrier reached the translator, which
connected to the same IPv4 Cloudflare endpoint. Only WARP's outer connection
needed IPv6; client traffic stayed IPv4 and required no DNS64 configuration.
The translator was level66.services, not the separate operator at nat64.net.

The successful path depended on the TCP adapter. Setting the synthesized IPv6
endpoint directly in r14 did not complete WARP setup in QEMU, even after basic
TCP reachability worked; the cause remains unresolved. Translator availability,
sustained-use policy and bandwidth limits were not established by this test.

**Psiphon** used the official Linux core built from
[commit 4ced7316](https://github.com/Psiphon-Labs/psiphon-tunnel-core/tree/4ced7316ef3eab90e24ac694f15dd0fb9231de66),
requesting Germany as its carrier country. It carried WARP's outer TCP connection
through its local SOCKS interface. This was **WARP inside Psiphon**: Cloudflare
remained the final exit. Only Germany was tested; requesting a Psiphon country
did not provide control over a specific Cloudflare location.

The stripped Psiphon binary was **21.1 MiB**. A small lab sample measured about
**23 MiB process RSS** and **1.5 MiB state**. These are additional costs, not total
container measurements or production limits. Three session handshakes advertised
zero rate limits; the [core's notice semantics](https://github.com/Psiphon-Labs/psiphon-tunnel-core/blob/4ced7316ef3eab90e24ac694f15dd0fb9231de66/psiphon/notice.go#L1036-L1040)
mean no cap at establishment and do not report later changes. No sustained
throughput or unlimited-service claim follows.

Psiphon's [service terms](https://psiphon.ca/en/license.html) distinguish its
open-source code from access to the public network and restrict personal versus
commercial use and third-party clients/tools. A distributed integration would
require clarification of permitted service use; this experiment does not establish
that permission.

## Failure, recovery and limits

Interrupting each lab carrier made the gateway stop answering ping and blocked
a fixed-IP client request without direct-WAN fallback. Restoring the carrier
recovered WARP without a CLI reconnect or daemon restart:

| Carrier | Time to unhealthy after interruption | Time to container health after restoration |
| --- | ---: | ---: |
| NAT64 | 8.57 s | 27.74 s |
| Psiphon | 12.27 s | 27.5 s |

In both cases, the first forwarded DNS/trace check after container health returned
timed out. NAT64's next check passed around 38 seconds after restoration. RouterOS
gateway checks can lag container readiness; the contribution of route timing
versus DNS was not isolated. The first Psiphon trace failure gated out Telegram
probes entirely, so it is not counted as a successful set. The later follow-up
sets in the table passed.

These were bounded transport and protocol checks. Phone login, message/media
delivery, calls, sustained throughput, long outages and long-term region stability
were not validated. UDP DNS travelled inside WARP over TCP; it does not establish
native Psiphon UDP or WARP-over-QUIC behavior for these arrangements.

## Final disposition

All temporary pilot proxy, NAT and filter objects were removed. Configuration
comparison matched the baseline, and the production WARP process and registration
were unchanged and healthy at cleanup. Lab defaults were restored, and temporary
VMs and helper processes were stopped. This experiment changed no released image.

Standard keeps its existing official client, internal checks, recovery and
administrator-owned routing. **Neither NAT64 nor Psiphon is bundled, selected
automatically or required by the installer.** Packaging, forwarding and health
integration bugs remain project issues. The project makes no promise to repair
every upstream path.

This report contains sanitized aggregate results. Raw router configuration,
registrations, private relay data and diagnostic captures remain outside the
public repository and release assets.
