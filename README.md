# MikroWARP

Run Cloudflare's official WARP client on MikroTik RouterOS in one container.
MikroWARP provides a WARP gateway with connection monitoring and automatic recovery.

## Install

Requires **x86-64 CHR with RouterOS 7.23+**, the matching container package,
container device mode enabled, and working Internet access. IPv4 traffic is supported.

Paste these two commands into the RouterOS terminal:

```routeros
/tool fetch url="https://github.com/parhamfa/mikrowarp/releases/latest/download/mikrowarp.rsc" dst-path=mikrowarp.rsc check-certificate=yes http-max-redirect-count=5
/import mikrowarp.rsc
```

Wait for **Ready. Gateway …**, then use the printed gateway address in your own
routes. You decide which traffic goes through WARP; installation leaves your
existing traffic on its current routes. The gateway answers ping only while its
connectivity checks pass.

Run the same two commands to update to the latest release.

[Documentation](documentation/README.md) · [Third-party notices](NOTICE.md)
