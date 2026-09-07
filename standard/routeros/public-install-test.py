#!/usr/bin/env python3
"""Reset a dedicated local QEMU CHR and exercise the public two-command install.

Developer acceptance only. Requires the existing loopback lab and native install;
the QEMU process, directory, SSH port and router identity are checked first.
"""
import hashlib
import json
import re
import subprocess
import time

from acceptance import Acceptance
from build import DEFAULT
from labctl import ROOT, lab, upload
from router import quote

t = Acceptance()
assert lab.ROUTER_PORT in (23222, 23223)
assert t.base in ('mikrowarp', 'pcie1/mikrowarp')
assert t.read(t.base + '/owner.txt') == t.config['owner']
t.stable_footprint()
assert len(t.r.rows('/system/script/job')) == 1, 'Another router operation is active'
for row in t.r.rows('/container'):
    assert t.config['owner'] in row.get('comment', '')
t.r.run('/container/stop [find where name="mikrowarp"]')
t.wait(lambda: t.r.rows('/container')[0].get('stopped'), 120)
t.r.run('/container/set [find where name="mikrowarp"] start-on-boot=no restart-policy=no; '
        '/container/remove [find where name="mikrowarp"]')
t.wait(lambda: not t.r.rows('/container'), 180)


def remove_owned_tree():
    try:
        t.r.run('/file/remove [find where name=' + quote(t.base) + ']')
    except RuntimeError:
        return False
    return not t.r.rows('/file', 'name=' + quote(t.base))


t.wait(remove_owned_tree, 180)
for path in ('mikrowarp-installation.json', 'mikrowarp.rsc', 'mikrowarp-last-operation.txt'):
    t.r.run('/file/remove [find where name=' + quote(path) + ']')
bootstrap = ROOT / 'runtime/routeros-installer/native-lab-bootstrap.rsc'
assert bootstrap.exists()
upload(bootstrap, 'native-lab-bootstrap.rsc')
# RouterOS reset clears only this disposable VM's configuration. The lab login
# and bootstrap are retained so testing can continue without a serial password.
try:
    t.r.run('/system/reset-configuration no-defaults=yes skip-backup=yes keep-users=yes '
            'run-after-reset=native-lab-bootstrap.rsc', timeout=20)
except (RuntimeError, subprocess.TimeoutExpired):
    pass
time.sleep(15)
# Reset regenerates the disposable router's SSH host key. Trust only this
# loopback endpoint while the matching, locally launched QEMU process is alive.
def refresh_lab_host_key():
    assert lab.running('router') and lab.ROUTER_PORT in (23222, 23223)
    scan = subprocess.run(['ssh-keyscan', '-T', '10', '-p', str(lab.ROUTER_PORT),
                           '-t', 'rsa', '127.0.0.1'], capture_output=True, text=True, timeout=15)
    keys = [line for line in scan.stdout.splitlines()
            if line.startswith('[127.0.0.1]:' + str(lab.ROUTER_PORT) + ' ssh-rsa ')]
    if scan.returncode or not keys:
        return False
    (lab.OUT / 'known_hosts').write_text('\n'.join(keys) + '\n')
    return True


t.wait(refresh_lab_host_key, 180)
t.wait(lambda: t.r.run(':put [/system/identity/get name]') == 'mikrowarp-native-lab', 180)
assert not t.r.rows('/container')
assert not t.r.rows('/file', 'name="mikrowarp-installation.json"')


def export():
    # Even terse exports wrap long escaped values such as container health output.
    text = re.sub(r'\\\r?\n[ \t]*', '', t.r.run('/export terse'))
    return [line for line in text.splitlines() if line and not line.startswith('#')]


before = export()
(lab.OUT / 'public-install-before-private.json').write_text(json.dumps(before, indent=2) + '\n')
fetch = ('/tool fetch url="https://raw.githubusercontent.com/parhamfa/mikrowarp/main/'
         'deploy/mikrotik/mikrowarp.rsc" dst-path=mikrowarp.rsc check-certificate=yes')
started = time.monotonic()
print('Fresh local CHR: fetching the public installer', flush=True)
t.r.run(fetch, timeout=120)
script = t.read('mikrowarp.rsc') + '\n'
assert script == (ROOT / 'deploy/mikrotik/mikrowarp.rsc').read_text()
print('Importing the public installer; router downloads the release image', flush=True)
output = t.r.run('/import mikrowarp.rsc', timeout=1800)
assert 'Ready. Gateway ' in output and 'RESULT success' in output, output[-2000:]
t = Acceptance()
assert t.image() == DEFAULT['image_id']
assert t.ready()
t.stable_footprint()
after = export()
(lab.OUT / 'public-install-after-private.json').write_text(json.dumps(after, indent=2) + '\n')
unrelated = [line for line in after if 'MikroWARP | ' not in line
             and not (line.startswith(('/container envs add ', '/container mounts add '))
                      and 'list=mikrowarp' in line)]
assert before == unrelated, '\n'.join(unrelated)
assert not t.r.rows('/file', 'name~"router-result|[.]partial"')
assert not t.r.rows('/file', 'name~"^mikrowarp-operation-[0-9a-f]+[.]txt"')
vendor = t.shell('cd /; sha256sum -c /usr/share/mikrowarp/warp-binaries.sha256')[1]
assert vendor.count(': OK') == 4
elapsed = round(time.monotonic() - started, 1)
t.case('public-two-command-install', lambda: {
    'source_url': fetch.split('"')[1], 'installer_sha256': hashlib.sha256(script.encode()).hexdigest(),
    'duration_seconds': elapsed, 'selected_directory': t.base, 'gateway': t.config['gateway'],
    'direct_release_download': True, 'certificate_checked': True, 'image_id_verified': True,
    'four_vendor_hashes_verified': True, 'unrelated_configuration_unchanged': True,
    'no_temporary_objects': True, 'no_persistent_scripts_schedulers_or_netwatch': True})
t.case('same-release-repeat', t.repeat)
print(t.output)
