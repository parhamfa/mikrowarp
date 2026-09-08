# Reference image source

The main build obtains and verifies the preserved base automatically. See
[development](../../docs/building.md); users never run these recipes themselves.

`base/` assembles the original Linux filesystem and unmodified Cloudflare
executables. The Dockerfile in this directory adds the reference routing wrapper.
Historical labels identify the exact inputs expected by the final Dockerfile.

For a deliberate base-reconstruction experiment:

```sh
docker build --platform linux/amd64 -t local/warp-masque-gateway:2026.7.1377.0-r10 tools/reference/base
docker build --platform linux/amd64 -t local/warp-masque-gateway:2026.7.1377.0-r11-pilot tools/reference
```

These commands may produce a different base ID because package repositories and
base tags can change. Use a separate Docker context for the experiment; do not
replace the verified reference used for release builds. A new base requires its
own validation and a deliberate update to the pinned identity.
