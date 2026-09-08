#!/usr/bin/env python3
"""Behavioral faults for the immutable candidate, on dedicated Docker resources."""
import datetime
import json
from pathlib import Path
import subprocess
import time

from . import docker_checks as c
OUT=c.OUT/('native-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
OUT.mkdir()
report={'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cases':[]}

def save(): (OUT/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
def wait(fn,seconds=240):
    until=time.monotonic()+seconds
    while time.monotonic()<until:
        if fn(): return
        time.sleep(3)
    raise TimeoutError('Behavior did not reach expected state')
def must(result):
    if result['code']: raise RuntimeError(result['out']+' '+result['error'])
    return result['out']
def remove_fault(): c.gateway('nft delete table inet mw_test_fault 2>/dev/null || true')
def add_fault(rule):
    remove_fault()
    must(c.gateway("nft -f - <<'EOF'\ntable inet mw_test_fault {\n chain forward {\n type filter hook forward priority -30; policy accept;\n "+rule+"\n }\n}\nEOF"))
def https():
    return c.client("curl --noproxy '*' -4 --resolve github.com:443:140.82.112.4 --connect-timeout 3 --max-time 8 -sS https://github.com/robots.txt -o /dev/null -w '%{http_code}'")
def case(name,fn):
    row={'name':name,'status':'incomplete'};report['cases'].append(row);save()
    try: row.update(fn() or {});row['status']='pass'
    except Exception as exc: row['status']='fail';row['error']=str(exc);raise
    finally: save();print(name+': '+row['status'],flush=True)

def baseline():
    wait(c.ready);assert c.ping();result=https();assert result['code']==0 and result['out']=='200',result
    report['image_id']=json.loads(subprocess.check_output(['docker','inspect',c.GATEWAY]))[0]['Image']
    return {'github_fixed_destination':result,'gateway_ping':True,'gateway':c.gateway('/usr/local/sbin/mikrowarp')['out']}

def cf_only():
    try:
        add_fault('iifname { "eth0", "mwprobe" } oifname "CloudflareWARP" ip daddr != { 1.1.1.1, 104.16.0.0/13 } counter drop;')
        wait(lambda:not c.ready(),70)
        trace=c.gateway("/usr/local/libexec/mikrowarp-io netns curl --noproxy '*' -4 -fsS --resolve cloudflare.com:443:104.16.133.229 --max-time 8 https://cloudflare.com/cdn-cgi/trace | grep '^warp='")
        status=c.gateway('/usr/local/sbin/mikrowarp');service=c.gateway('warp-cli --accept-tos status')
        assert trace['code']==0 and trace['out']=='warp=on',trace
        assert 'external_ipv4_0_of_3' in status['out'],status
        assert not c.ping();failed=https();assert failed['code']!=0,failed
        return {'cloudflare_trace':trace['out'],'service':service['out'],'gateway':status['out'],'non_cf_failed':True}
    finally: remove_fault();wait(c.ready)

def dns_fault():
    try:
        add_fault('iifname "mwprobe" udp dport 53 counter drop;')
        wait(lambda:not c.ready(),70);assert not c.ping()
        return {'gateway':c.gateway('/usr/local/sbin/mikrowarp')['out']}
    finally:remove_fault();wait(c.ready)

def one_dns():
    try:
        add_fault('iifname "mwprobe" ip daddr 9.9.9.9 udp dport 53 counter drop;')
        wait(lambda:'dns_1_of_2' in c.gateway('/usr/local/sbin/mikrowarp')['out'],90)
        assert c.ready() and c.ping()
        return {'gateway':c.gateway('/usr/local/sbin/mikrowarp')['out']}
    finally:remove_fault();wait(c.ready)

def frozen_controller():
    wait(c.ready);assert c.ping()
    pid=int(must(c.gateway('cat /run/mikrowarp/controller.pid')))
    before=json.loads(subprocess.check_output(['docker','inspect',c.GATEWAY]))[0]['RestartCount']
    identity=must(c.gateway('sha256sum /var/lib/mikrowarp/state/reg.json')).split()[0]
    started=time.monotonic()
    try:
        must(c.gateway('kill -STOP '+str(pid)))
        time.sleep(35);service=c.gateway('warp-cli --accept-tos status')
        time.sleep(30)
        assert not c.ready() and not c.ping()
        result=https();assert result['code']!=0,result
        arp=c.client('ip neigh show 172.30.114.2');assert 'lladdr' in arp['out']
        wait(lambda:json.loads(subprocess.check_output(['docker','inspect',c.GATEWAY]))[0]['RestartCount']>before,150)
        wait(c.ready,240)
        assert must(c.gateway('sha256sum /var/lib/mikrowarp/state/reg.json')).split()[0]==identity
        return {'at_65_seconds':'ping and fixed-IP HTTPS blocked; ARP retained','service_at_35s':service['out'],
                'automatic_recovery_s':round(time.monotonic()-started,1),'registration_preserved':True}
    finally:c.gateway('kill -CONT '+str(pid)+' 2>/dev/null || true')

def daemon_crash():
    wait(c.ready)
    identity=must(c.gateway('sha256sum /var/lib/mikrowarp/state/reg.json')).split()[0]
    pid=int(must(c.gateway('cat /run/mikrowarp/warp.pid')))
    must(c.gateway('kill -KILL '+str(pid)))
    wait(lambda:not c.ready(),45);wait(c.ready,240)
    assert int(must(c.gateway('cat /run/mikrowarp/warp.pid')))!=pid
    assert must(c.gateway('sha256sum /var/lib/mikrowarp/state/reg.json')).split()[0]==identity
    return {'registration_preserved':True,'recovered_without_intervention':True}

try:
    case('baseline',baseline)
    case('Cloudflare reachable but other IPv4 blocked',cf_only)
    case('all forwarded UDP DNS blocked',dns_fault)
    case('one DNS provider unavailable',one_dns)
    case('controller freeze and automatic recovery',frozen_controller)
    case('warp-svc crash and recovery',daemon_crash)
finally:
    remove_fault();report['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
