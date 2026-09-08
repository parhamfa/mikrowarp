#!/usr/bin/env python3
"""Bounded disk-pressure tests on disposable tmpfs mounts, never host disk filling."""
import argparse
import datetime
import json
from pathlib import Path
import subprocess
import time

OUT=Path(__file__).resolve().parents[2]/'runtime/standard-r14'
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--bundle',type=Path,required=True)
a=p.parse_args()
IMAGE=json.loads(a.bundle.read_text())['image_id']
REPORT=OUT/('storage-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
cases=[]

def run(command,tmpfs='size=4m'):
    r=subprocess.run(['docker','run','--rm','--platform','linux/amd64','--network','none',
                      '--tmpfs','/scratch:'+tmpfs,'--entrypoint','/bin/bash',IMAGE,'-ec',command],
                     capture_output=True,text=True,timeout=45)
    if r.returncode: raise RuntimeError(r.stdout+r.stderr)
    return r.stdout.strip()

def record(name,fn):
    row={'name':name,'status':'incomplete'};cases.append(row)
    try: row['result']=fn();row['status']='pass'
    except Exception as exc:row['status']='fail';row['error']=str(exc);raise
    finally:
        REPORT.write_text(json.dumps({'image_id':IMAGE,'cases':cases},indent=2)+'\n')
        print(name+': '+row['status'],flush=True)

record('32 MiB log stream retained as two 1 MiB files',lambda:run('''
head -c 33554432 /dev/zero | /usr/local/libexec/mikrowarp-io log /scratch 1048576
test "$(find /scratch -type f | wc -l)" = 2
test "$(stat -c %s /scratch/service.log)" = 1048576
test "$(stat -c %s /scratch/service.log.1)" = 1048576
du -sk /scratch
'''))
record('full log filesystem drains output without hanging',lambda:run('''
head -c 33554432 /dev/zero | /usr/local/libexec/mikrowarp-io log /scratch 1048576
test "$(du -sk /scratch | awk '{print $1}')" -le 1024
echo producer_completed
''','size=1m'))
record('log symlink cannot overwrite a different file',lambda:run('''
printf sentinel > /scratch/protected
ln -s /scratch/protected /scratch/service.log
head -c 1048576 /dev/zero | /usr/local/libexec/mikrowarp-io log /scratch 1048576
test "$(cat /scratch/protected)" = sentinel
echo protected_file_unchanged
'''))
record('known output pruned while registration and unknown state survive',lambda:run('''
mkdir -p /var/lib/mikrowarp/{state,logs,diagnostics}
printf registration_fixture > /var/lib/mikrowarp/state/reg.json
printf unknown_fixture > /var/lib/mikrowarp/state/unknown-state
head -c 3145728 /dev/zero > /var/lib/mikrowarp/state/cfwarp_service_log.txt
head -c 34603008 /dev/zero > /var/lib/mikrowarp/diagnostics/warp-debugging-info-large.zip
touch -d '2 days ago' /var/lib/mikrowarp/diagnostics/warp-debugging-info-old.zip
touch /var/lib/mikrowarp/diagnostics/warp-debugging-info-recent.zip
/usr/local/lib/mikrowarp/storage.sh
test "$(cat /var/lib/mikrowarp/state/reg.json)" = registration_fixture
test "$(cat /var/lib/mikrowarp/state/unknown-state)" = unknown_fixture
test ! -s /var/lib/mikrowarp/state/cfwarp_service_log.txt
test ! -e /var/lib/mikrowarp/diagnostics/warp-debugging-info-large.zip
test ! -e /var/lib/mikrowarp/diagnostics/warp-debugging-info-old.zip
test -e /var/lib/mikrowarp/diagnostics/warp-debugging-info-recent.zip
echo registration_and_unknown_state_preserved
'''))

def low_space():
    name='mikrowarp-r14-space-test';owner='123456789012345678901234567890ab'
    script='printf %s "$MIKROWARP_STATE_ID" > /var/lib/mikrowarp/owner.txt; exec /usr/local/libexec/mikrowarp-io supervise /usr/local/lib/mikrowarp/gateway.sh'
    subprocess.run(['docker','run','-d','--platform','linux/amd64','--name',name,'--network','mikrowarp-r14-uplink',
        '--privileged','--tmpfs','/var/lib/mikrowarp:size=32m','-e','MIKROWARP_STATE_ID='+owner,
        '--entrypoint','/bin/bash',IMAGE,'-c',script],check=True,capture_output=True)
    try:
        until=time.monotonic()+45;out=''
        while time.monotonic()<until:
            r=subprocess.run(['docker','exec',name,'cat','/run/mikrowarp/status'],capture_output=True,text=True)
            out=r.stdout
            if 'storage_low' in out:break
            time.sleep(2)
        assert 'storage_low' in out,out
        r=subprocess.run(['docker','exec',name,'bash','-ec','! pgrep -x warp-svc; test ! -e /var/lib/mikrowarp/state/reg.json; nft list set inet mikrowarp ready'],capture_output=True,text=True)
        assert r.returncode==0,r.stdout+r.stderr
        return 'Service held before registration on a 32 MiB state filesystem; readiness empty.'
    finally:
        subprocess.run(['docker','stop','-t','10',name],capture_output=True)
        subprocess.run(['docker','rm','-v',name],check=True,capture_output=True)

record('low free space prevents daemon and registration creation',low_space)
