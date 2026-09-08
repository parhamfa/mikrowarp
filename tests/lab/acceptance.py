#!/usr/bin/env python3
"""Destructive native-installer acceptance on the dedicated loopback CHR only.

This is developer test tooling, never part of installation or router operation.
Reports and fixture installers go to the ignored runtime directory.
"""
import argparse
import datetime
import hashlib
import ipaddress
import json
from pathlib import Path
import subprocess
import sys
import time

from .control import ROOT, lab, upload
from tools.installer import DEFAULT, render
from .transport import Router, quote

OUT = ROOT / 'runtime/routeros-installer'


class Acceptance:
    def __init__(self, release=DEFAULT):
        self.release = release
        assert lab.running('router'), 'Dedicated QEMU router must be running'
        self.r = Router({'host': '127.0.0.1', 'port': lab.ROUTER_PORT, 'user': 'admin',
                         'key': str(lab.OUT / 'key'), 'known_hosts': str(lab.OUT / 'known_hosts'),
                         'identity': 'mikrowarp-native-lab'})
        self.r.run(':put "local lab confirmed"')
        self.config = json.loads(self.read('mikrowarp-installation.json'))
        self.base = self.config['directory']
        self.report = {'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                       'routeros': self.r.run(':put [/system/resource/get version]'), 'cases': []}
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        self.output = OUT / ('acceptance-' + str(lab.ROUTER_PORT) + '-' + stamp + '.json')

    def read(self, path):
        return self.r.run(':put [/file/get [find where name=' + quote(path) + '] contents]')

    def journal(self):
        records = []
        for slot in (0, 1):
            try:
                envelope = json.loads(self.read(self.base + '/data/installer/operation.' + str(slot) + '.json'))
                checksum = 2166136261
                for byte in envelope['payload'].encode():
                    checksum = ((checksum ^ byte) * 16777619) & 0xffffffff
                assert checksum == envelope['checksum']
                records.append(json.loads(envelope['payload']))
            except (RuntimeError, ValueError, KeyError, AssertionError):
                pass
        assert records, 'No valid on-router journal'
        return max(records, key=lambda x: x['sequence'])

    def shell(self, command, check=True, timeout=60):
        return self.r.shell('mikrowarp', command, timeout=timeout, check=check)

    def ready(self):
        try:
            return self.shell('/usr/local/sbin/mikrowarp', check=False)[0] == 0
        except (RuntimeError, subprocess.TimeoutExpired):
            return False

    def wait(self, predicate, timeout=480):
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            try:
                if predicate():
                    return round(time.monotonic() - start, 1)
            except (RuntimeError, subprocess.TimeoutExpired):
                pass
            time.sleep(3)
        raise TimeoutError('Acceptance condition did not recover')

    def client(self, command, timeout=30):
        assert lab.running('client')
        return lab.ssh('client', command, timeout=timeout)

    def native(self, action=None, script='mikrowarp.rsc', timeout=1800):
        command = (':global mikrowarpAction ' + quote(action) + '; ') if action else ''
        command += '/import ' + quote(script)
        result = self.r.run(command, timeout=timeout)
        assert 'RESULT success' in result, result[-1000:]
        return result

    def reg(self):
        return self.shell('sha256sum /var/lib/mikrowarp/state/reg.json')[1].split()[0]

    def image(self):
        return self.r.run(':put [/container/get [find where name="mikrowarp"] image-id]')

    def stable_footprint(self):
        rows = self.r.rows('/container')
        assert len(rows) == 1 and rows[0]['name'] == 'mikrowarp', rows
        assert len(self.r.rows('/system/script')) == len(self.r.rows('/system/scheduler')) == len(self.r.rows('/tool/netwatch')) == 0
        assert not self.r.rows('/system/script/environment', 'name~"^mikrowarpNative"')
        assert not self.r.rows('/file', 'name="mikrowarp-operation.lock.json"')
        for menu, count in (('/ip/firewall/nat', 1), ('/ip/firewall/filter', 3)):
            assert len([r for r in self.r.rows(menu) if self.config['owner'] in r.get('comment', '')]) == count

    def case(self, name, run):
        print(name + ': running', flush=True)
        result = {'name': name, 'result': 'incomplete'}
        self.report['cases'].append(result)
        try:
            result.update(run() or {})
            result['result'] = 'pass'
        except Exception as e:
            result.update(result='fail', error=str(e)[-2000:])
            raise
        finally:
            self.output.write_text(json.dumps(self.report, indent=2) + '\n')
            print(name + ': ' + result['result'], flush=True)

    def repeat(self):
        self.wait(self.ready)
        before = self.shell('cat /run/mikrowarp/controller.pid; cat /run/mikrowarp/warp.pid')[1]
        registration = self.reg()
        state = self.journal()
        self.native(script='sibling.rsc' if state['current']['image_id'] != self.release['image_id'] else 'mikrowarp.rsc')
        self.native('status')
        assert self.shell('cat /run/mikrowarp/controller.pid; cat /run/mikrowarp/warp.pid')[1] == before
        assert self.reg() == registration and self.journal()['sequence'] == state['sequence']
        assert self.r.run(':global mikrowarpAction; :put [:typeof $mikrowarpAction]') == 'nothing'
        self.stable_footprint()
        return {'processes_unchanged': True, 'journal_unchanged': True, 'action_consumed': True}

    def rollback(self):
        before = self.journal()
        expected = before['previous']['bundle']['image_id']
        label = before['previous']['snapshot']
        expected_reg = self.shell('tar -xOf /var/lib/mikrowarp/recovery/' + label + '.tar state/reg.json | sha256sum')[1].split()[0]
        self.native('rollback')
        self.wait(self.ready)
        assert self.image() == expected
        assert self.reg() == expected_reg
        self.stable_footprint()
        return {'expected_image_restored': True, 'snapshot_registration_restored': True, 'healthy': True}

    def forwarded(self):
        self.wait(self.ready)
        self.r.run('/import native-lab-admin-policy.rsc')
        self.client('ip addr replace 198.18.14.10/24 dev eth0')
        self.wait(lambda: self.client('ping -c 1 -W 2 ' + self.config['gateway'], 6).returncode == 0, 120)
        answer = self.client('dig +short github.com A @1.1.1.1').stdout.splitlines()
        addresses = []
        for item in answer:
            try:
                addresses.append(str(ipaddress.IPv4Address(item)))
            except ipaddress.AddressValueError:
                pass
        assert addresses, answer
        github = addresses[0]
        data = []
        # Start with the non-private source and cold PMTU information. A prior
        # private-source request can otherwise mask missing ICMP size feedback.
        assert self.client('ip route flush cache').returncode == 0
        for source in ('198.18.14.10', '192.168.88.10'):
            for url, resolve in [('https://github.com/robots.txt', '--resolve github.com:443:' + github),
                                 ('https://www.google.com/generate_204', '')]:
                attempts = []
                for attempt in range(3):
                    r = self.client('curl -4 --noproxy "*" --interface ' + source + ' -fsS ' + resolve +
                                    ' --connect-timeout 10 --max-time 20 ' + url + ' -o /dev/null -w "%{http_code}"')
                    attempts.append({'code': r.returncode, 'http': r.stdout, 'error': r.stderr.strip()})
                    if r.returncode == 0 and r.stdout in ('200', '204'):
                        break
                    time.sleep(3)
                assert r.returncode == 0 and r.stdout in ('200', '204'), (source, url, resolve, attempts, data)
                data.append({'source': source, 'url': url, 'status': r.stdout, 'attempts': attempts})
            traces = []
            for attempt in range(3):
                r = self.client('curl -4 --noproxy "*" --interface ' + source +
                                ' -fsS --max-time 20 https://cloudflare.com/cdn-cgi/trace | grep "^warp="')
                traces.append({'code': r.returncode, 'result': r.stdout.strip(), 'error': r.stderr.strip()})
                if r.returncode == 0 and r.stdout.strip() == 'warp=on':
                    break
                time.sleep(3)
            assert r.returncode == 0 and r.stdout.strip() == 'warp=on', (source, traces)
            data.append({'source': source, 'warp_trace_attempts': traces})
        for source in ('198.18.14.10', '192.168.88.10'):
            for resolver in ('1.1.1.1', '9.9.9.9'):
                r = self.client('dig -b ' + source + ' +time=5 +tries=2 @' + resolver + ' example.com A')
                assert r.returncode == 0 and 'status: NOERROR' in r.stdout, r.stdout
        return {'https': data, 'warp': 'on', 'udp_dns': ['1.1.1.1', '9.9.9.9'],
                'udp_dns_sources': ['198.18.14.10', '192.168.88.10'], 'cold_pmtu': True}

    def unselected(self):
        assert not self.r.rows('/routing/rule', 'table="lab-warp"'), 'Run before adding lab traffic policy'
        attempts = []
        for attempt in range(3):
            result = self.client('curl -4 --noproxy "*" --interface 192.168.88.10 -fsS '
                                 '--connect-timeout 10 --max-time 20 '
                                 'https://cloudflare.com/cdn-cgi/trace | grep "^warp="')
            attempts.append({'code': result.returncode, 'trace': result.stdout.strip(),
                             'error': result.stderr.strip()})
            if result.returncode == 0 and result.stdout.strip() == 'warp=off':
                return {'client_uses_existing_uplink': True, 'warp_trace_attempts': attempts}
            time.sleep(3)
        raise AssertionError(attempts)

    def bulk(self):
        self.wait(self.ready)
        archive = ROOT / 'dist/routeros-native/mikrowarp-standard-r14-linux-amd64.tar.gz'
        with archive.open('rb') as source:
            expected = hashlib.sha256(source.read(1048576)).hexdigest()
        command = ('curl -4 --noproxy "*" --interface 198.18.14.10 -fLsS '
                   '--connect-timeout 10 --max-time 60 --range 0-1048575 --max-filesize 1048576 '
                   + self.release['url'] + ' -o /tmp/mikrowarp-range.bin -w "%{http_code}"')
        result = self.client(command, 70)
        assert result.returncode == 0 and result.stdout == '206', (result.stdout, result.stderr)
        value = self.client('sha256sum /tmp/mikrowarp-range.bin; wc -c < /tmp/mikrowarp-range.bin; '
                            'rm /tmp/mikrowarp-range.bin').stdout.splitlines()
        assert value[0].split()[0] == expected and value[1].strip() == '1048576', value
        return {'bytes': 1048576, 'sha256_matched': True, 'http': 206, 'source': '198.18.14.10'}

    def pmtu(self):
        self.wait(self.ready)
        assert self.image() == self.release['image_id'], 'Negative control is specific to pinned Standard r14'
        addresses = self.client('dig +short www.google.com A @1.1.1.1').stdout.splitlines()
        addresses = [str(ipaddress.IPv4Address(x)) for x in addresses if x and x[0].isdigit()][:4]
        assert addresses
        registration = self.reg()
        processes = self.shell('cat /run/mikrowarp/controller.pid; cat /run/mikrowarp/warp.pid')[1]

        def request(address):
            result = self.client('curl -4 --noproxy "*" --interface 198.18.14.10 '
                                 '--resolve www.google.com:443:' + address + ' --connect-timeout 10 '
                                 '--max-time 20 -fsS https://www.google.com/generate_204 '
                                 '-o /dev/null -w "%{http_code}"')
            return {'ip': address, 'code': result.returncode, 'http': result.stdout}

        try:
            self.r.run('/interface/bridge/set [find where name="mikrowarp-link"] mtu=1500')
            assert self.client('ip route flush cache').returncode == 0
            before = request(addresses[0])
            assert before['code'] == 28, before
        finally:
            self.native()
        assert self.reg() == registration
        assert self.shell('cat /run/mikrowarp/controller.pid; cat /run/mikrowarp/warp.pid')[1] == processes
        assert self.client('ip route flush cache').returncode == 0
        self.client('timeout 8 tcpdump -U -ni eth0 -w /tmp/mikrowarp-pmtu.pcap "icmp" '
                    '>/tmp/mikrowarp-pmtu-capture.txt 2>&1 </dev/null &')
        after = [request(address) for address in addresses]
        assert all(row['code'] == 0 and row['http'] == '204' for row in after), after
        time.sleep(8)
        capture = self.client('tcpdump -nn -r /tmp/mikrowarp-pmtu.pcap; '
                              'rm -f /tmp/mikrowarp-pmtu.pcap /tmp/mikrowarp-pmtu-capture.txt').stdout
        assert 'mtu 1300' in capture.lower(), capture
        return {'negative_control_at_1500': before, 'first_attempts_at_1300': after,
                'icmp_size_feedback_received': True, 'processes_and_registration_unchanged': True}

    def service_crash(self):
        self.wait(self.ready)
        registration = self.reg()
        pid = int(self.shell('cat /run/mikrowarp/warp.pid')[1])
        self.shell('kill -KILL ' + str(pid))
        self.wait(lambda: not self.ready(), 60)
        elapsed = self.wait(self.ready, 480)
        assert self.reg() == registration
        return {'automatic_recovery_seconds': elapsed, 'registration_preserved': True}

    def health_fault(self, kind):
        self.wait(self.ready)
        registration = self.reg()
        rule = ('iifname { "eth0", "mwprobe" } oifname "CloudflareWARP" '
                'ip daddr != { 1.1.1.1, 104.16.0.0/13 } counter drop;' if kind == 'cf-only' else
                'iifname "mwprobe" udp dport 53 counter drop;')
        self.shell('nft delete table inet mw_native_test 2>/dev/null || true')
        result = {}
        try:
            self.shell("nft -f - <<'EOF'\ntable inet mw_native_test {\n chain forward {\n "
                       'type filter hook forward priority -30; policy accept;\n ' + rule + '\n }\n}\nEOF')
            self.wait(lambda: not self.ready(), 100)
            status = self.shell('/usr/local/sbin/mikrowarp', check=False)[1]
            assert self.r.run(':put [/ping ' + self.config['gateway'] + ' count=2 interval=200ms]').splitlines()[-1] == '0'
            if kind == 'cf-only':
                trace = self.shell('/usr/local/libexec/mikrowarp-io netns curl -4 --noproxy "*" '
                                   '--resolve cloudflare.com:443:104.16.133.229 -fsS --max-time 15 '
                                   'https://cloudflare.com/cdn-cgi/trace | grep "^warp="')[1]
                assert trace == 'warp=on' and 'external_ipv4_0_of_3' in status, (trace, status)
                assert 'Connected' in self.shell('warp-cli --accept-tos status')[1]
                result['cloudflare_reachable_while_non_cf_blocked'] = True
            else:
                # Blocking probe DNS also prevents HTTPS hostname resolution.
                assert 'state=unready' in status, status
                assert 'udp dport 53' in self.shell('nft list table inet mw_native_test')[1]
                result['probe_udp_dns_blocked'] = True
            assert self.r.rows('/ip/arp', 'address=' + quote(self.config['gateway']))
            self.wait(lambda: bool(self.r.rows('/ip/route', 'comment="R14 LAB ADMIN | Chosen blackhole fallback"')[0].get('active')), 60)
            r = self.client('curl -4 --noproxy "*" --resolve www.google.com:443:142.251.155.119 '
                            '--connect-timeout 3 --max-time 7 -fsS https://www.google.com/generate_204 -o /dev/null')
            assert r.returncode != 0
            result.update(gateway_ping_withdrawn=True, arp_retained=True, administrator_blackhole_active=True,
                          client_traffic_blocked=True, monitor_status=status)
        finally:
            self.shell('nft delete table inet mw_native_test', check=False)
            self.wait(self.ready)
        assert self.reg() == registration
        result['automatic_recovery'] = True
        return result

    def controller_freeze(self):
        self.wait(self.ready)
        registration = self.reg()
        pid = int(self.shell('cat /run/mikrowarp/controller.pid')[1])
        start = time.monotonic()
        try:
            self.shell('kill -STOP ' + str(pid))
            time.sleep(65)
            assert not self.ready()
            assert self.r.run(':put [/ping ' + self.config['gateway'] + ' count=2 interval=200ms]').splitlines()[-1] == '0'
            assert self.r.rows('/ip/arp', 'address=' + quote(self.config['gateway']))
            self.wait(self.ready, 480)
            assert self.reg() == registration
            return {'kernel_health_expired': True, 'gateway_ping_withdrawn': True, 'arp_retained': True,
                    'automatic_recovery_seconds': round(time.monotonic() - start, 1), 'registration_preserved': True}
        finally:
            self.shell('kill -CONT ' + str(pid) + ' 2>/dev/null || true', check=False)

    def reboot(self, without_wan=False):
        self.wait(self.ready)
        registration = self.reg()
        if without_wan:
            lab.qmp('router', 'set_link', {'name': 'wan', 'up': False})
        try:
            lab.qmp('router', 'system_reset')
            time.sleep(8)
            if without_wan:
                # Management SSH uses the WAN emulation too. Observe the LAN
                # while it is down, then restore the link before using SSH.
                time.sleep(60)
                assert self.client('ping -c 1 -W 3 192.168.88.1', 8).returncode == 0
                assert self.client('ping -c 1 -W 3 ' + self.config['gateway'], 8).returncode != 0
        finally:
            if without_wan:
                lab.qmp('router', 'set_link', {'name': 'wan', 'up': True})
        self.wait(lambda: self.r.run(':put "alive"') == 'alive', 180)
        elapsed = self.wait(self.ready, 480)
        assert self.reg() == registration
        return {'automatic_recovery_seconds': elapsed, 'registration_preserved': True, 'no_reimport': True}

    def fixture(self, metadata, name, pause=None):
        text = render(metadata)
        if pause:
            needle = '    $mikrowarpNativeLog text=("Phase: " . $phase)'
            assert text.count(needle) == 1
            text = text.replace(needle, needle + '\n    :if ($phase = "' + pause + '") do={ :delay 50s }')
        path = OUT / (name + '.rsc')
        path.write_text(text)
        upload(path, path.name)
        return path.name

    def rejected_candidate(self, kind):
        self.wait(self.ready)
        before = self.journal()
        registration = self.reg()
        expected_image = self.image()
        metadata = dict(self.release)
        if kind == 'truncated':
            metadata.update(image_id='a' * 64, sha256='b' * 64, revision='lab-truncated',
                            url='https://raw.githubusercontent.com/parhamfa/mikrowarp/main/NOTICE.md')
            match = 'Download size does not match'
        elif kind == 'wrong-id':
            metadata.update(image_id='c' * 64, revision='lab-wrong-id')
            match = 'image ID does not match'
        else:
            raw = json.loads((ROOT / 'runtime/standard-r14/lab-broken/image.json').read_text())
            metadata.update({key: raw[key] for key in ('sha256', 'archive_bytes', 'logical_bytes')})
            metadata.update(image_id=raw['image_id'].removeprefix('sha256:'), revision='lab-broken',
                            url='https://example.invalid/private-lab-broken.tar.gz')
            upload(ROOT / 'runtime/standard-r14/lab-broken/image.tar.gz',
                   self.base + '/archives/' + metadata['sha256'] + '.tar.gz')
            match = 'Candidate rejected'
        filename = self.fixture(metadata, 'native-' + kind)
        try:
            self.native(script=filename)
        except RuntimeError as e:
            assert match in str(e), str(e)[-2000:]
        else:
            raise AssertionError('Invalid candidate was accepted')
        if kind != 'broken':
            assert self.image() == expected_image and self.ready()
            if kind == 'wrong-id':
                row = self.r.rows('/container', 'name="mikrowarp-next"')[0]
                assert row.get('stopped') and not self.r.run(':put [/container/get [find where name="mikrowarp-next"] start-on-boot]') == 'true'
            self.native('abort')
        self.wait(self.ready)
        assert self.image() == expected_image and self.reg() == registration
        assert self.journal()['previous'] == before['previous']
        assert not self.r.rows('/file', 'name~"[.]partial"')
        self.stable_footprint()
        self.r.run('/file/remove [find where name=' + quote(filename) + ']')
        return {'candidate_rejected': True, 'previous_image_and_registration_preserved': True,
                'cleanup_complete': True, 'automatic_rollback': kind == 'broken'}

    def terminal_disconnect(self):
        self.wait(self.ready)
        registration = self.reg()
        sibling = json.loads((OUT / 'sibling.json').read_text())
        target = sibling if self.image() == self.release['image_id'] else self.release
        archive = ROOT / ('runtime/standard-r14/lab-sibling/image.tar.gz' if target == sibling else
                          'dist/routeros-native/mikrowarp-standard-r14-linux-amd64.tar.gz')
        upload(archive, self.base + '/archives/' + target['sha256'] + '.tar.gz')
        name = self.fixture(target, 'terminal-disconnect', pause='staging')
        with open(OUT / 'terminal-disconnect-private.txt', 'w') as log:
            proc = subprocess.Popen(lab.ssh_args('router') + ['admin@127.0.0.1', '/import ' + name], stdout=log, stderr=log)
            self.wait(lambda: self.journal()['phase'] == 'staging', 180)
            try:
                self.native('status')
            except RuntimeError as e:
                assert 'another operation is running' in str(e)
            else:
                raise AssertionError('Concurrent import was not refused')
            proc.terminate()
            proc.wait(timeout=10)
            self.wait(lambda: self.journal()['phase'] == 'complete', 1200)
        time.sleep(3)
        name = self.fixture(target, 'terminal-complete')
        self.native(script=name)
        assert self.image() == target['image_id'] and self.reg() == registration and self.ready()
        self.stable_footprint()
        self.r.run('/file/remove [find where name="terminal-disconnect.rsc"]; /file/remove [find where name="terminal-complete.rsc"]')
        return {'terminal_closed': True, 'concurrent_import_refused': True, 'background_completion': True,
                'next_import_reclaimed_lock': True, 'registration_preserved': True}

    def interrupted_update(self, phase):
        before = self.journal()
        registration = self.reg()
        sibling = json.loads((OUT / 'sibling.json').read_text())
        target = sibling if before['current']['image_id'] == self.release['image_id'] else self.release
        # Keep private fixture archives offline. Actual production HTTPS download
        # is tested separately by the unmodified two-command public quickstart.
        archive = 'runtime/standard-r14/lab-sibling/image.tar.gz' if target == sibling else 'dist/routeros-native/mikrowarp-standard-r14-linux-amd64.tar.gz'
        if not self.r.rows('/file', 'name=' + quote(self.base + '/archives/' + target['sha256'] + '.tar.gz')):
            upload(ROOT / archive, self.base + '/archives/' + target['sha256'] + '.tar.gz')
        filename = self.fixture(target, 'fault-' + phase, pause=phase)
        log = open(OUT / ('fault-' + phase + '-private.txt'), 'w')
        proc = subprocess.Popen(lab.ssh_args('router') + ['admin@127.0.0.1', '/import ' + filename], stdout=log, stderr=log)
        try:
            self.wait(lambda: self.journal()['phase'] == phase, 900)
            lab.qmp('router', 'system_reset')
            time.sleep(8)
            self.wait(lambda: self.r.run(':put "alive"') == 'alive', 180)
            filename = self.fixture(target, 'resume-' + phase)
            self.native(script=filename)
            self.wait(self.ready)
            assert self.image() == target['image_id'] and self.reg() == registration
            self.stable_footprint()
            return {'reboot_phase': phase, 'reimport_completed': True, 'registration_preserved': True}
        finally:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=10)
            log.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('cases', nargs='+', choices=['repeat', 'rollback', 'forwarded', 'unselected', 'bulk', 'pmtu', 'service', 'reboot', 'offline-boot',
                                               'staging', 'quiescing', 'switching', 'validating', 'committing',
                                               'truncated', 'wrong-id', 'broken', 'terminal', 'cf-only', 'dns-fault', 'controller'])
    a = p.parse_args()
    t = Acceptance()
    methods = {'repeat': t.repeat, 'rollback': t.rollback, 'forwarded': t.forwarded, 'unselected': t.unselected, 'bulk': t.bulk, 'pmtu': t.pmtu,
               'service': t.service_crash, 'reboot': t.reboot, 'offline-boot': lambda: t.reboot(True),
               'truncated': lambda: t.rejected_candidate('truncated'), 'wrong-id': lambda: t.rejected_candidate('wrong-id'),
               'broken': lambda: t.rejected_candidate('broken'), 'terminal': t.terminal_disconnect,
               'cf-only': lambda: t.health_fault('cf-only'), 'dns-fault': lambda: t.health_fault('dns-fault'),
               'controller': t.controller_freeze}
    for name in a.cases:
        t.case(name, methods[name] if name in methods else lambda n=name: t.interrupted_update(n))
    print(t.output)
