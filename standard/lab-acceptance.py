#!/usr/bin/env python3
"""Destructive tests ONLY on the named, loopback QEMU laboratory."""
import datetime
import json
from pathlib import Path
import subprocess
import time
import lab
from manage import Manager,wait_for

OUT=lab.OUT/('chr-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
OUT.mkdir()
p=json.loads((lab.OUT/'profile.json').read_text())
assert p['host']=='127.0.0.1' and p['port']==23222 and p['identity']=='mikrowarp-standard-lab'
assert lab.running('router') and lab.running('client')
m=Manager(p)
report={'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cases':[]}

def save(): (OUT/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
def client(command,timeout=45):
    r=lab.ssh('client',command,timeout)
    return {'code':r.returncode,'out':r.stdout.strip(),'error':r.stderr.strip()}
def shell(command,check=True,timeout=45):return m.r.shell('mikrowarp',command,check=check,timeout=timeout)
def ping():return client('ping -c 1 -W 2 172.31.242.2',8)['code']==0
def trace(source='192.168.88.10'):
    return client('curl --noproxy "*" -4 --interface '+source+' -fsS --max-time 12 https://cloudflare.com/cdn-cgi/trace | grep "^warp="',20)
def https(source='192.168.88.10'):
    return client('curl --noproxy "*" -4 --interface '+source+' -fsS --resolve github.com:443:140.82.112.4 --connect-timeout 4 --max-time 10 https://github.com/robots.txt -o /dev/null -w "%{http_code}"',18)
def registration(): return shell('sha256sum /var/lib/mikrowarp/state/reg.json')[1].split()[0]
def case(name,fn):
    row={'name':name,'status':'incomplete'};report['cases'].append(row);save()
    try:row.update(fn() or {});row['status']='pass'
    except Exception as exc:row['error']=str(exc);row['status']='fail';raise
    finally:save();print(name+': '+row['status'],flush=True)
def router_online():
    try:return m.r.run(':put [/system/identity get name]')==p['identity']
    except (RuntimeError,subprocess.TimeoutExpired):return False
def route_active():
    rows=m.rows('/ip/route','comment="R14 LAB ADMIN | WARP route"')
    return bool(rows and rows[0].get('active'))

def footprint():
    wait_for(m.ready,420)
    row=m.container();report['image_id']=row['image-id'];report['routeros']=m.rows('/system/resource')[0]['version']
    counts={menu:len(m.rows(menu)) for menu in ('/ip/firewall/address-list','/ip/firewall/mangle','/routing/rule','/tool/netwatch','/system/script','/system/scheduler')}
    assert all(value==0 for value in counts.values()),counts
    assert len(m.rows('/container'))==1
    assert [x['name'] for x in m.rows('/routing/table')]==['main']
    baseline=trace();assert baseline['out']=='warp=off',baseline
    filters=m.rows('/ip/firewall/filter');nats=m.rows('/ip/firewall/nat')
    owned_filters=[x for x in filters if p['owner'] in x.get('comment','')]
    owned_nats=[x for x in nats if p['owner'] in x.get('comment','')]
    assert len(owned_filters)==3 and len(owned_nats)==1
    return {'empty_menus':counts,'owned_filters':3,'owned_nat':1,'ordinary_client_before_routing':baseline['out'],
            'gateway':shell('/usr/local/sbin/mikrowarp')[1]}

def forwarded():
    m.r.copy(str(lab.ROOT/'standard/lab-admin-policy.rsc'),'r14-admin-policy.rsc')
    m.r.run('/import file-name=r14-admin-policy.rsc')
    client('ip addr add 198.18.14.10/24 dev eth0 2>/dev/null || true')
    wait_for(route_active,90)
    assert ping()
    results={}
    for source in ('192.168.88.10','198.18.14.10'):
        result=https(source);assert result['code']==0 and result['out']=='200',result
        evidence=trace(source);assert evidence['out']=='warp=on',evidence
        results[source]={'github':200,'warp':evidence['out']}
    for resolver in ('1.1.1.1','9.9.9.9'):
        result=client('nslookup -type=A example.com '+resolver,12)
        assert result['code']==0 and 'example.com' in result['out'],result
        results['udp_dns_'+resolver]='pass'
    return results

def controller_failure():
    wait_for(m.ready);before=registration();pid=int(shell('cat /run/mikrowarp/controller.pid')[1])
    started=time.monotonic()
    try:
        shell('kill -STOP '+str(pid))
        time.sleep(35);service=shell('warp-cli --accept-tos status')[1]
        time.sleep(30)
        assert not ping() and not m.ready()
        wait_for(lambda:not route_active(),40)
        blackhole=m.rows('/ip/route','comment="R14 LAB ADMIN | Chosen blackhole fallback"')[0]
        assert blackhole.get('active'),blackhole
        blocked=https();assert blocked['code']!=0,blocked
        arp=m.rows('/ip/arp','address="172.31.242.2"');assert arp
        wait_for(m.ready,300);wait_for(route_active,60)
        assert registration()==before and ping()
        return {'service_while_controller_frozen':service,'kernel_lease_expired':True,
                'administrator_route_withdrawn':True,'administrator_blackhole_active':True,
                'arp_preserved':True,'fixed_ip_https_blocked':True,'registration_preserved':True,
                'automatic_recovery_s':round(time.monotonic()-started,1)}
    finally:
        try:shell('kill -CONT '+str(pid)+' 2>/dev/null || true',check=False)
        except RuntimeError:pass

def service_crash():
    wait_for(m.ready);before=registration();pid=int(shell('cat /run/mikrowarp/warp.pid')[1])
    shell('kill -KILL '+str(pid))
    wait_for(lambda:not m.ready(),45);wait_for(m.ready,300);wait_for(route_active,60)
    assert registration()==before and int(shell('cat /run/mikrowarp/warp.pid')[1])!=pid
    assert https()['out']=='200'
    return {'registration_preserved':True,'forwarding_recovered':True}

def wan_outage():
    wait_for(m.ready);before=registration();started=time.monotonic()
    try:
        lab.qmp('router','set_link',{'name':'wan','up':False})
        wait_for(lambda:not ping(),70)
        assert https()['code']!=0
        time.sleep(15)
    finally:lab.qmp('router','set_link',{'name':'wan','up':True})
    wait_for(router_online,90);wait_for(m.ready,360);wait_for(route_active,60)
    assert registration()==before and https()['out']=='200'
    return {'gateway_ping_withdrawn':True,'registration_preserved':True,'outage_and_recovery_s':round(time.monotonic()-started,1)}

def reboot():
    wait_for(m.ready);before=registration();started=time.monotonic()
    try:m.r.run('/system/reboot',timeout=15)
    except (RuntimeError,subprocess.TimeoutExpired):pass
    time.sleep(15);wait_for(router_online,90);wait_for(m.ready,360);wait_for(route_active,60)
    assert registration()==before and https()['out']=='200'
    return {'registration_preserved':True,'automatic_start_and_forwarding':True,'recovery_s':round(time.monotonic()-started,1)}

def boot_without_wan():
    wait_for(m.ready);before=registration();started=time.monotonic()
    try:
        lab.qmp('router','set_link',{'name':'wan','up':False})
        lab.qmp('router','system_reset')
        time.sleep(45)
        assert not ping() and https()['code']!=0
        time.sleep(15)
    finally:lab.qmp('router','set_link',{'name':'wan','up':True})
    wait_for(router_online,90);wait_for(m.ready,420);wait_for(route_active,60)
    assert registration()==before and https()['out']=='200'
    return {'abrupt_reset_with_wan_disconnected':True,'gateway_did_not_advertise_readiness':True,
            'registration_preserved':True,'automatic_recovery_s':round(time.monotonic()-started,1)}

try:
    case('fresh installation leaves traffic policy untouched',footprint)
    case('administrator-routed private and non-private clients',forwarded)
    case('frozen controller expires ping and route; automatic restart',controller_failure)
    case('service crash recovers without registration replacement',service_crash)
    case('WAN loss and restoration',wan_outage)
    case('normal router reboot',reboot)
    case('abrupt reset, boot without Internet, restore Internet',boot_without_wan)
finally:
    if lab.running('router'):lab.qmp('router','set_link',{'name':'wan','up':True})
    report['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
