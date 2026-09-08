# Publishing a release

Users fetch the installer through GitHub's permanent latest-release link.
The installer is a release asset named `mikrowarp.rsc`; each published copy pins
an image belonging to that same release. A later release does not change an
installer that was already downloaded or automatically update a running router.

Use version tags such as `v1.0.0`, followed by new versions for later releases.
Keep published versions and their assets unchanged so an earlier installer can
still obtain its matching image. Use GitHub's latest-release designation for the
current supported version, rather than moving an existing version tag.

Each release contains:

- `mikrowarp.rsc` and its SHA-256 file.
- `mikrowarp-linux-amd64.tar.gz` and its SHA-256 file.

## Release checks

1. Prepare an empty-state image and verify its identity, archive integrity and
   vendor binaries. Reusing an already tested image means copying its exact bytes;
   a new label inside an image creates a different image and requires validation.
2. Update the release URL, label and verified image metadata in
   `standard/routeros/build.py`. The URL must point to a specific version's image,
   not to a moving latest-image alias. Render the installer and check it with
   `python3 standard/routeros/build.py --check`.
3. Create a draft release from the reviewed commit and attach all four assets.
   Verify their names, sizes and checksums before publishing.
4. Publish the complete release and designate it as latest. Verify anonymous
   downloads and exercise the README's exact two commands on a disposable CHR.
   Confirm the downloaded installer matches the release, the image passes its
   checks, forwarding works and repeat import preserves the healthy process.
5. Update the public documentation and record validation. Never test disruptive
   installation or recovery on a production router.

This keeps the user's commands stable while preserving the installer's pinned
image checks and stored rollback state. Old experimental assets remain available
as build inputs and historical references; users do not need to select them.

GitHub documents the [latest-release download link](https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases#linking-to-the-latest-release)
and [release publishing](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository).
