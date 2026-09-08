#!/usr/bin/env python3
"""Private QEMU acceptance console; deliberately cannot select a real router."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
from . import vm as lab

variant = os.environ.get('MIKROWARP_LAB_VARIANT', 'v723')
assert variant in ('v723', 'v7235')
lab.OUT = ROOT / 'runtime/routeros-installer' / variant
if variant == 'v7235':
    lab.ROUTER_PORT = 23223
    lab.CLIENT_PORT = 23023
    lab.WINBOX_PORT = 29292
    lab.LAN_PORT = 13001


def command(text, timeout=60):
    if not lab.running('router'):
        raise RuntimeError('The dedicated local QEMU router is not running')
    return lab.ssh('router', text, timeout=timeout)


def upload(path, destination):
    if not lab.running('router'):
        raise RuntimeError('The dedicated local QEMU router is not running')
    subprocess.run(lab.ssh_args('router', scp=True) +
                   [str(path), 'admin@127.0.0.1:' + destination], check=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', nargs='?', default=':put [/system/identity/get name]')
    p.add_argument('--upload', type=Path)
    p.add_argument('--destination', default='mikrowarp.rsc')
    p.add_argument('--timeout', type=int, default=60)
    p.add_argument('--save', type=Path)
    a = p.parse_args()
    if a.upload:
        upload(a.upload, a.destination)
    r = command(a.command, a.timeout)
    if a.save:
        a.save.write_text(r.stdout + r.stderr)
    print(r.stdout, end='')
    print(r.stderr, end='', file=sys.stderr)
    raise SystemExit(r.returncode)
