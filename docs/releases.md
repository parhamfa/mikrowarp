# Releases

The README's permanent latest-release link downloads `mikrowarp.rsc`. Each copy
of that installer pins one version-specific image URL and its validation metadata.
Publishing a release does not update containers already running on routers.

## Prepare a candidate

After the [source checks and build](building.md):

```sh
make release VERSION=v1.0.1
```

This verifies `dist/build/`, copies its image without changing any bytes, and
generates the matching installer and checksums in `dist/release/`. Set `OUT` and
`RELEASE_OUT` to use different input and output directories. Existing output is
never overwritten. The command only prepares local files.

Each public release has four assets:

- `mikrowarp.rsc` and `mikrowarp.rsc.sha256`
- `mikrowarp-linux-amd64.tar.gz` and `mikrowarp-linux-amd64.tar.gz.sha256`

The extra `metadata.json` is developer input for testing and installer generation;
it is not required by users and is not attached to the public release.

Pushing a new version tag runs the **Draft release** workflow: source checks,
build, archive verification and candidate packaging, followed by a draft GitHub
release. It never replaces existing assets or promotes a candidate to latest.
The **Checks** workflow also runs on branches and pull requests.

## Validate and publish

1. Test the exact candidate image and installer on disposable local CHRs. Cover
   installation, repeat import, forwarded non-Cloudflare IPv4, UDP DNS, service
   recovery and matching-image/state rollback. Use the [lab harness](../tests/README.md);
   a successful source check or Docker build alone is not runtime acceptance.
2. Verify the four uploaded assets against their local sizes and SHA-256 values.
   Keep the release a draft until candidate validation is complete. Draft assets
   are not anonymously downloadable: lab validation can preload the verified image
   archive in the installer's cache, but that does not prove the public download path.
3. Publish the complete release without making it latest. On a disposable CHR,
   fetch its version-specific installer over certificate-checked HTTPS and verify
   the router downloads the matching image successfully. Check forwarding and
   repeat import. If this fails, keep the previous release as latest.
4. Update `DEFAULT` in `tools/installer.py` from the candidate's `metadata.json`,
   run `make installer` and `make check`, and commit that current-release snapshot.
   Mark the validated release as latest and exercise the README's exact commands
   with `python3 -m tests.lab.public_install`. Record the results under `docs/archive/`.

Never run destructive acceptance tests on a production router. Normal source
reorganization should keep the generated installer and runtime source unchanged;
it does not require a new container release.

## Preserve earlier releases

Use immutable version tags such as `v1.0.1`; do not move a tag called `latest`.
GitHub's latest-release designation supplies the stable user-facing URL. Preserve
published tags and assets so stored installers and rollback records keep working.
Historical build assets remain available because the current build references one.

GitHub documents [latest-release links](https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases#linking-to-the-latest-release)
and [release publishing](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository).
