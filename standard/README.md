# Runtime and developer tools

This directory contains the container runtime, image exporter and disposable
lab tools. The directory name is an internal source path, not a separate edition.

- [Install and manage MikroWARP](../documentation/usage.md)
- [Build the tested image](../build/README.md)
- [RouterOS installer source](routeros/README.md)
- [Research and validation archive](../documentation/archive/README.md)

The lab harnesses are developer tools. Disruptive tests must use disposable local
QEMU VMs, never a production router. Users install directly from RouterOS.
