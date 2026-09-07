#!/usr/bin/env python3
"""Negative installation tests on a fresh, loopback-only QEMU CHR."""
import datetime
import json
import time

from labctl import ROOT, lab
from router import Router

assert lab.running('router')
r = Router({'host': '127.0.0.1', 'port': lab.ROUTER_PORT, 'user': 'admin',
            'key': str(lab.OUT / 'key'), 'known_hosts': str(lab.OUT / 'known_hosts'),
            'identity': 'mikrowarp-native-lab'})
assert not r.rows('/file', 'name="mikrowarp-installation.json"')
report = {'routeros': r.run(':put [/system/resource/get version]'), 'cases': []}


def config():
    return '\n'.join(line for line in r.run('/export terse').splitlines() if not line.startswith('#'))


def reject(name, match, setup='', options='', cleanup=''):
    if setup:
        r.run(setup)
    try:
        before = config()
        try:
            r.run(options + '/import mikrowarp.rsc', timeout=180)
        except RuntimeError as e:
            assert match in str(e), str(e)
        else:
            raise AssertionError('Expected refusal: ' + name)
        assert config() == before, 'Router configuration changed on a rejected preflight'
        assert not r.rows('/file', 'name="mikrowarp-installation.json"')
        assert not r.rows('/file', 'name="mikrowarp-operation.lock.json"')
        assert not r.rows('/system/script/environment', 'name~"^mikrowarpNative"')
        report['cases'].append({'name': name, 'result': 'pass', 'unrelated_configuration_unchanged': True})
        print(name + ': pass', flush=True)
    finally:
        if cleanup:
            r.run(cleanup)
        path = ROOT / 'runtime/routeros-installer/preflight-private.json'
        path.write_text(json.dumps(report, indent=2) + '\n')


reject('occupied interface name', 'Interface name is occupied',
       '/interface/bridge/add name=mikrowarp-link comment="NATIVE LAB | occupied name"',
       cleanup='/interface/bridge/remove [find where comment="NATIVE LAB | occupied name"]')
reject('occupied subnet override', 'overlaps existing',
       '/ip/address/add address=172.31.242.1/30 interface=ether2 comment="NATIVE LAB | occupied subnet"',
       ':global mikrowarpOptions {"network"="172.31.242.0/30"}; ',
       '/ip/address/remove [find where comment="NATIVE LAB | occupied subnet"]')
reject('invalid subnet input', 'Transit network must',
       options=':global mikrowarpOptions {"network"="not-a-network"}; ')
reject('occupied storage path', 'Storage directory already exists',
       '/file/add name=pcie1/native-occupied type=directory',
       ':global mikrowarpOptions {"directory"="pcie1/native-occupied"}; ',
       '/file/remove [find where name="pcie1/native-occupied"]')
reject('insufficient internal storage override', 'enough staging space',
       options=':global mikrowarpOptions {"directory"="native-too-small"}; ')
reject('unknown management action', 'action must', options=':global mikrowarpAction "invalid"; ')

# Keep the original WAN and add a distinct active uplink on the empty second NIC.
reject('ambiguous active uplinks', 'uplink',
       '/ip/route/add dst-address=0.0.0.0/0 gateway=ether2 distance=1 comment="NATIVE LAB | ambiguous uplink"',
       cleanup='/ip/route/remove [find where comment="NATIVE LAB | ambiguous uplink"]')

reject('no writable storage', 'Not enough writable storage',
       '/disk/set pcie1 mount-filesystem=no; :delay 2s',
       cleanup='/disk/set pcie1 mount-filesystem=yes; :delay 2s')
print('Fresh-install negative checks complete')
