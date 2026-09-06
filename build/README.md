# Build MikroWARP Standard

Normal users should download the installation bundle. These instructions are for
developers building the container with Docker and Python 3.11+.

## Use the exact release reference

The r14 build deliberately checks the identity of its r11 reference. Download
`build-only-r11-base.tar.gz`, its `.sha256` file and `.json` metadata from the
[r14 release](https://github.com/parhamfa/mikrowarp/releases/tag/r14-standard).
This is a build input, not an additional container to install on a router.

```sh
shasum -a 256 -c build-only-r11-base.tar.gz.sha256
docker load -i build-only-r11-base.tar.gz
docker image inspect local/warp-masque-gateway:2026.7.1377.0-r11-pilot --format '{{.Id}}'
```

Expected image ID:
`sha256:cd6cb165c8e780cfa700cf300e2a4aa64158b7992c888326830e75cf5b4236b2`

From the repository root:

```sh
python3 standard/bundle.py --build --output dist/my-build
```

This builds for `linux/amd64`, verifies the four retained Cloudflare binary
hashes, and exports `image.tar.gz`, `image.json` and a checksum file. Export also
verifies gzip integrity, the image configuration and every layer. Existing output
archives are not overwritten. A new build is a new candidate requiring validation;
timestamps and build-stage dependencies can produce a different image ID.

## Reference source

The original reference can be assembled from the source in this repository:

```sh
docker build --platform linux/amd64 -f container/Dockerfile.minimal -t local/warp-masque-gateway:2026.7.1377.0-r10 container
docker build --platform linux/amd64 -t local/warp-masque-gateway:2026.7.1377.0-r11-pilot build/reference
```

The first stage downloads the pinned official WARP package through signed APT
metadata and assembles the required Ubuntu/glibc files. The second adds the
historical local-routing wrapper. Package repositories and base tags can change,
so these commands are **not a bit-for-bit rebuild promise**. A regenerated base
will not necessarily match the release's required ID. Use the published build
input to work from the tested reference; a new base needs a deliberate version
change and a fresh acceptance run.

The local QEMU/Docker harnesses under `standard/` require prepared disposable
fixtures. They are development equipment and are not run by the installer.
Never point destructive tests at a production router.
