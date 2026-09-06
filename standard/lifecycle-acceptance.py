#!/usr/bin/env python3
"""Update fault tests restricted to the named loopback QEMU laboratory."""
import datetime
import json
from pathlib import Path
import subprocess
import time

import lab
from lifecycle import Lifecycle
from manage import Manager, wait_for

OUT=lab.OUT/('lifecycle-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
OUT.mkdir()
p=json.loads((lab.OUT/'profile.json').read_text())
assert p['host']=='127.0.0.1' and p['port']==23222 and p['identity']=='mikrowarp-standard-lab'
assert lab.running('router') and lab.running('client')
m=Lifecycle(p)
accepted=json.loads((lab.OUT/'rc4/image.json').read_text())
sibling=json.loads((lab.OUT/'lab-sibling/image.json').read_text())
report={'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'image_id':accepted['image_id'],'cases':[]}

def save(): (OUT/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
def shell(command): return m.r.shell('mikrowarp',command)[1]
def registration(): return shell('sha256sum /var/lib/mikrowarp/state/reg.json').split()[0]
def canary(value=None):
    path='/var/lib/mikrowarp/state/lab-rollback-canary'
    if value is not None:
        assert value.isalnum()
        shell('printf '+value+' > '+path)
    return shell('cat '+path)
def healthy():
    wait_for(m.ready,420)
    result=lab.ssh('client','curl -4 --noproxy "*" --resolve github.com:443:140.82.112.4 --connect-timeout 5 --max-time 15 -fsS https://github.com/robots.txt -o /dev/null -w "%{http_code}"',25)
    assert result.returncode==0 and result.stdout.strip()=='200',result.stderr
    assert len(m.rows('/container'))==1
def cli(action,bundle=None,expected=0):
    args=['python3',str(lab.ROOT/'standard/manage.py'),action,'--profile',str(lab.OUT/'profile.json')]
    if bundle: args+=['--bundle',str(bundle/'image.json'),'--archive',str(bundle/'image.tar.gz')]
    logfile=OUT/(str(len(report['cases']))+'-'+action+'-private.log')
    with logfile.open('w') as f: result=subprocess.run(args,stdout=f,stderr=subprocess.STDOUT,timeout=1200)
    assert (result.returncode==0)==(expected==0),f'{action} returned {result.returncode}; inspect private log'
def case(name,fn):
    item={'name':name,'status':'incomplete'};report['cases'].append(item);save();started=time.monotonic()
    try:item.update(fn() or {});item['status']='pass'
    except Exception as exc:item['status']='fail';item['error']=str(exc);raise
    finally:item['elapsed_s']=round(time.monotonic()-started,1);save();print(name+': '+item['status'],flush=True)
def inventory():
    menus=('/container','/interface/bridge','/interface/veth','/interface/bridge/port','/ip/address',
           '/ip/firewall/filter','/ip/firewall/nat','/ip/firewall/mangle','/ip/firewall/address-list',
           '/routing/table','/routing/rule','/tool/netwatch','/system/script','/system/scheduler')
    return {menu:[row['.id'] for row in m.rows(menu)] for menu in menus}

def idempotent():
    before=inventory();started=shell("awk '{print $22}' /proc/1/stat");reg=registration()
    cli('install',lab.OUT/'rc4')
    assert inventory()==before and shell("awk '{print $22}' /proc/1/stat")==started
    assert registration()==reg;healthy()
    return {'same_router_objects':True,'container_not_restarted':True,'registration_preserved':True}

def guards():
    before=inventory()
    wrong=dict(p,owner='0'*32)
    try:Manager(wrong).preflight(accepted)
    except RuntimeError as exc:assert 'owned' in str(exc)
    else:raise AssertionError('Wrong storage owner was accepted')
    wrong=dict(p,network='192.168.88.0/30')
    try:Manager(wrong).preflight(accepted)
    except RuntimeError as exc:assert 'overlap' in str(exc)
    else:raise AssertionError('Overlapping subnet was accepted')
    low=Manager(p);real=low.rows
    def limited(menu,condition=''):
        rows=real(menu,condition)
        if menu=='/system/resource':return [dict(rows[0],**{'free-hdd-space':1024})]
        if menu=='/disk':return []
        return rows
    low.rows=limited
    try:low.preflight(accepted)
    except RuntimeError as exc:assert 'Insufficient staging space' in str(exc)
    else:raise AssertionError('Insufficient free space was accepted')
    m.r.claim()
    try:
        try:Lifecycle(p).r.claim()
        except RuntimeError as exc:assert 'Another administrator' in str(exc)
        else:raise AssertionError('Concurrent operation acquired the lease')
    finally:m.r.release()
    assert inventory()==before and not m.rows('/system/script/environment','name="mikrowarpAdminLock"')
    return {'ownership_conflict':'rejected','address_overlap':'rejected','simulated_low_free_space':'rejected',
            'concurrent_administrator':'rejected','router_objects_unchanged':True}

def interrupted_update():
    reg=registration();canary('baseline4')
    original=m.save_job
    def interrupt(job,phase):
        result=original(job,phase)
        if phase=='switching':raise KeyboardInterrupt('Lab interruption after durable state snapshot')
        return result
    m.save_job=interrupt;m.r.claim()
    try:
        try:m.begin_update(lab.OUT/'lab-sibling/image.tar.gz',sibling)
        except KeyboardInterrupt:pass
        else:raise AssertionError('Interruption was not reached')
    finally:m.save_job=original;m.r.release()
    assert m.pending()['phase']=='switching' and not m.ready()
    assert 'state=maintenance' in shell('/usr/local/sbin/mikrowarp || true')
    cli('resume');healthy()
    assert m.record('installed')['image_id']==sibling['image_id'] and registration()==reg
    assert canary()=='baseline4'
    return {'interrupted_after_snapshot':True,'maintenance_retained':True,'resume_completed':True,'registration_preserved':True}

def rollback():
    reg=registration();canary('changed4');cli('rollback');healthy()
    assert m.record('installed')['image_id']==accepted['image_id']
    assert canary()=='baseline4' and registration()==reg
    return {'previous_image_restored':True,'matching_state_snapshot_restored':True,'registration_preserved':True}

def broken_candidate():
    reg=registration();canary('beforebad4')
    cli('update',lab.OUT/'lab-broken',expected=1);healthy()
    assert m.journal()['phase']=='aborted' and m.record('installed')['image_id']==accepted['image_id']
    assert canary()=='beforebad4' and registration()==reg
    assert not m.file_exists(m.archive_path(json.loads((lab.OUT/'lab-broken/image.json').read_text())))
    return {'candidate_exit_code':42,'automatically_aborted':True,'old_image_and_state_restored':True,'failed_archive_removed':True}

try:
    assert m.record('installed')['image_id']==accepted['image_id'] and not m.pending()
    healthy()
    case('same-release install is idempotent',idempotent)
    case('ownership, address, free-space and concurrency guards',guards)
    case('interrupted update resumes from durable snapshot',interrupted_update)
    case('rollback restores image and matching saved state',rollback)
    case('broken candidate automatically restores accepted image',broken_candidate)
finally:
    report['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
