# Testing

`make check` runs offline checks. It never starts a VM, changes a router or connects
to Cloudflare. `make test` runs only the Python unit tests.

The modules in `tests/lab/` are explicitly invoked developer acceptance tests.
They are not part of installation or runtime, and they are not collected by the
unit-test command. QEMU tests accept only the named local fixtures on loopback.
Docker fault tests use fixed, disposable container names.

## Native RouterOS acceptance

The current harness uses prepared, private CHR fixtures under
`runtime/routeros-installer/v7235/` (RouterOS 7.23.5) or `v723/` (7.23.2).
It requires QEMU, SSH, a matching container package and enabled container device
mode. VM disks, login keys, registrations and raw reports are excluded from Git.
This harness is not yet a fixture downloader or a clean-machine lab bootstrap.

With the dedicated 7.23.5 fixture running and MikroWARP installed:

```sh
make test-lab
make test-lab CASES="repeat forwarded service"
MIKROWARP_LAB_VARIANT=v7235 python3 -m tests.lab.public_install
```

The last command resets the disposable CHR and exercises the README's exact
two-command installation. It must find the expected running QEMU process, local
port, router identity and owned installation before it can reset anything.

`make test-lab` defaults to the repeat-import check. Additional cases include
`unselected`, `bulk`, `pmtu`, `cf-only`, `dns-fault`, `controller`, `reboot`,
`offline-boot`, `rollback`, `truncated`, `wrong-id`, `broken`, `terminal` and the
update phases exposed by the acceptance module's `--help`. Some need a connected
client VM, a lab routing fixture or a second verified image. They are destructive
to these disposable fixtures and must not be redirected to production.

For a published candidate that is not yet latest, the public-install test also
accepts `--installer-url`, `--expected-installer` and `--metadata`; it still uses only the
dedicated local fixture. Without these options, it tests the README's latest URL
and compares the downloaded installer with the root `mikrowarp.rsc`.

`tests.lab.control` supplies the guarded lab console and file upload helpers.
`tests.lab.preflight` checks refusal cases on an already prepared, empty local CHR.
The small RouterOS examples under `tests/fixtures/` are administrator-owned lab
routing/bootstrap examples, not rules installed by MikroWARP.

## Runtime regression fixtures

`tests.lab.runtime_acceptance` and `tests.lab.continuity` retain the original
runtime's reboot, forwarding and transfer checks on its separate local fixture.
`tests.lab.gateway` contains only the read helpers those checks still need.
The former computer-side installer and its own lifecycle tests are preserved in
the [v1 source history](https://github.com/parhamfa/mikrowarp/tree/v1.0.0/standard);
installation and update testing now target the native RouterOS implementation.

`tests.lab.docker_acceptance`, `tests.lab.docker_checks` and `tests.lab.storage`
retain the dedicated Docker fault and disk-pressure checks. Their prepared
resources are developer fixtures, not extra production containers.

Keep raw results under `runtime/`; publish only sanitized summaries in
[the research archive](../docs/archive/README.md).
