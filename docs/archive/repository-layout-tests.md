# Repository layout validation

The September 8, 2026 cleanup separates runtime source, native installer source,
build tools, tests and documentation. It retires the public computer-side
installer while keeping the small read helpers used by existing runtime tests.

Validation of the reorganized source:

- All 15 offline unit tests passed locally and in GitHub's Linux Checks workflow.
  Checks also covered Python and shell syntax, ShellCheck, Linux C compilation,
  generated-installer consistency and relative documentation links.
- The generated installer, four RouterOS source fragments, container runtime
  source and assembler remain byte-for-byte identical to the previous checkout.
- The pinned reference archive was downloaded over HTTPS and verified against its
  size, SHA-256, image configuration and layer digests.
- The root Dockerfile built successfully, and the resulting archive passed
  independent configuration, blob, layer and gzip checks. Release packaging
  preserved that archive and generated matching installer/checksum assets.
- Comparing all 1,221 filesystem entries with the published image found identical
  programs, libraries, file permissions, ownership and symlinks. Build timestamps
  were excluded. The only content difference was key order in the provenance JSON;
  its parsed values and all recorded source hashes were identical.
- The relocated public-install test passed on the dedicated RouterOS 7.23.5 QEMU
  fixture using the README's exact two commands. It verified image identity, all
  four vendor binaries, fresh gateway readiness, unchanged unrelated configuration
  and no temporary installer objects. Repeat import preserved running processes,
  registration and the operation journal, and consumed the temporary action variable.

The rebuilt image was a local validation artifact. The existing v1 release image,
installer assets and latest-release installation URL were not replaced. No
production router was accessed. Raw fixture data and reports remain private.

The Draft release workflow is a candidate builder, not a replacement for live
RouterOS acceptance. Publishing a new image still requires the checks described
in the [release process](../releases.md).
