# Latest-release installation check

Tested on September 8, 2026, using a fresh disposable x86 CHR running
RouterOS 7.23.5. The production router was not involved.

The initial v1 release reuses the exact tested container archive. Local archive
verification passed gzip integrity, image identity and every layer hash. All four
uploaded release assets matched their local SHA-256 digests and sizes.

The permanent latest-release URL was checked anonymously and returned the exact
published installer. The CHR then ran the two commands shown in the main README:

- Certificate-checked download of the latest installer and its matching image passed.
- Imported image identity and all four Cloudflare binary hashes matched.
- The installer's forwarding checks passed before it reported the gateway ready.
- Unrelated router configuration remained unchanged; no temporary objects remained.
- Repeat import and status preserved the running processes, registration and journal.
- The temporary action variable was consumed, with no installed System scripts,
  schedulers or Netwatch monitors.

Installation took 333.1 seconds in the emulated lab.
The fresh-install and repeat-import cases both passed. This check validates the
release delivery path; it does not repeat or expand the earlier
[runtime](runtime-tests.md) and [installer](routeros-tests.md) fault matrices.

Only the installer's release URL and label changed. Container bytes, forwarding,
health checks and recovery behavior were unchanged. Raw router exports and
registration evidence remain private.
