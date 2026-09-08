# RouterOS installer source

For installation and management, use the [operation guide](../../documentation/usage.md).

`bootstrap.rsc`, `worker.rsc`, `operations.rsc` and `main.rsc` are the source.
`build.py` renders the downloadable `deploy/mikrotik/mikrowarp.rsc` installer
with a pinned release image and its validation metadata.

```sh
python3 standard/routeros/build.py
python3 standard/routeros/build.py --check
```

See the [release process](../../documentation/releases.md) for publishing.
The acceptance tools in this directory operate only on guarded local QEMU labs.
Their [recorded results](../../documentation/archive/routeros-tests.md) are separate
from the private VM disks, router configuration and registration data.
