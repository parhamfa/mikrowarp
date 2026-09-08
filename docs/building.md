# Development

For installation on a router, use the [two RouterOS commands](../README.md#install).
The tools below run on a developer's computer and do not ship in the container.

## Source layout

| Path | Responsibility |
| --- | --- |
| `src/container/` | Gateway startup, monitoring, recovery, storage and the C supervisor |
| `src/routeros/` | Source pieces of the native RouterOS installer |
| `Dockerfile` | The current container image recipe |
| `mikrowarp.rsc` | Generated installer for the current published release |
| `tools/` | Image assembly, export, installer generation and release packaging |
| `tests/` | Offline checks and explicitly invoked local lab tests |
| `docs/archive/` | Research, historical approaches and recorded validation |

## Check and build

Install Python 3.11+, Make, Bash and ShellCheck. Linux source checks also use a C
compiler. Building the image requires a running Docker daemon with Linux/AMD64
support; ARM development machines need AMD64 emulation.

```sh
make check
make build
```

`make check` runs offline source checks, verifies that the generated installer
matches its sources, checks documentation links and runs the unit tests. It
does not start containers, contact routers or require Docker.

`make build` obtains the pinned reference image if it is missing, verifies the
download's size, SHA-256, image configuration and layers, then builds and exports
the current image to `dist/build/`. The reference download is cached under
`dist/build-cache/`. There is no manual Docker image-loading step.

Exports include the image archive, its metadata and a checksum. An existing export
is never overwritten; use a fresh output directory for another candidate:

```sh
make build OUT=dist/next-candidate
```

The final image contains the runtime and all four official Cloudflare programs.
Python and the compiler are temporary build tools. Only the explicitly allowed
runtime files enter the Docker build context; private lab material is excluded.

## Installer changes

Edit the RouterOS source under `src/routeros/`, then regenerate the single installer:

```sh
make installer
make check
```

The current release metadata is in `tools/installer.py`. The installed image ID
and its release version are separate: changing an image label creates a new image,
while distributing the same verified archive under a new release preserves it.
The current installer snapshot retains its original header for byte-for-byte
comparison with the published asset; `make installer` is the supported generator.

See [lab testing](../tests/README.md) and the [release process](releases.md).

## Preserved reference

The current runtime deliberately builds on an exact, verified base. Its old
reference labels are provenance identifiers, not product editions. The automatic
download and expected identity are pinned in `tools/image.py`.

The corresponding base source is retained under `tools/reference/`. It is a build
input, not an additional container users run. Reconstructing that base from current
package repositories can produce different bytes; replacing the pinned base needs
its own image validation. This repository cleanup does not change the published image.
