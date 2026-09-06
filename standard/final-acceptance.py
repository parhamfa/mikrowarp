#!/usr/bin/env python3
"""Final boot, paced transfer and continuity checks on the loopback CHR only."""
import datetime
import json
from pathlib import Path
import shlex
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor

import lab
from lifecycle import Lifecycle
from manage import wait_for

p=json.loads((lab.OUT/'profile.json').read_text())
assert p['host']=='127.0.0.1' and p['port']==23222 and p['identity']=='mikrowarp-standard-lab'
assert lab.running('router') and lab.running('client')
m=Lifecycle(p)
bundle=json.loads((lab.OUT/'rc4/image.json').read_text())
OUT=lab.OUT/('final-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
OUT.mkdir()
report={'image_id':bundle['image_id'],'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cases':[]}
def save(): (OUT/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n')
def client(command,timeout=30):
    r=lab.ssh('client',command,timeout)
    return {'exit':r.returncode,'out':r.stdout.strip(),'error':r.stderr.strip()}
def shell(command,check=True):return m.r.shell('mikrowarp',command,check=check)[1]
def case(name,fn):
    row={'name':name,'status':'incomplete'};report['cases'].append(row);save()
    try:row.update(fn() or {});row['status']='pass'
    except Exception as exc:row.update(status='fail',error=str(exc));raise
    finally:save();print(name+': '+row['status'],flush=True)
def online():
    try:return m.r.run(':put [/system/identity get name]')==p['identity']
    except (RuntimeError,subprocess.TimeoutExpired):return False
def route():
    rows=m.rows('/ip/route','comment="R14 LAB ADMIN | WARP route"')
    return bool(rows and rows[0].get('active'))

def reboot():
    before=shell('sha256sum /var/lib/mikrowarp/state/reg.json').split()[0]
    started=time.monotonic()
    try:m.r.run('/system/reboot',timeout=15)
    except (RuntimeError,subprocess.TimeoutExpired):pass
    time.sleep(15);wait_for(online,120);wait_for(m.ready,420);wait_for(route,80)
    assert shell('sha256sum /var/lib/mikrowarp/state/reg.json').split()[0]==before
    assert len(m.rows('/container'))==1 and m.container()['image-id']==bundle['image_id'][7:]
    return {'automatic_start':True,'registration_preserved':True,'seconds':round(time.monotonic()-started,1)}

def paced_load():
    body=r'''
fetch() {
  line=$(curl --noproxy '*' -4sS --connect-timeout 6 --max-time 160 --range 0-2097151 --limit-rate 32K --proto '=https' --max-redirs 0 -o /dev/null -w '%{http_code} %{size_download} %{time_total}' https://fsn1-speed.hetzner.com/100MB.bin 2>/dev/null)
  rc=$?; printf '%s %s %s\n' "$1" "$rc" "$line"
}
fetch first & a=$!
fetch second & b=$!
wait "$a"; wait "$b"
printf 'DONE\n'
'''
    output='/tmp/mikrowarp-final-load.txt'
    r=client('setsid sh -c '+shlex.quote(body)+' </dev/null >'+output+' 2>&1 &',10)
    assert r['exit']==0,r
    sampling=':for i from=1 to=16 do={ :delay 5s; :put ([:tostr $i]." ".[:tostr [/system/resource get cpu-load]]." ".[:tostr [/container get [find where name="mikrowarp"] cpu-usage]]." ".[:tostr [/container get [find where name="mikrowarp"] memory-current]]) }'
    raw=m.r.run(sampling,timeout=100)
    samples=[]
    for line in raw.splitlines():
        n,cpu,container_cpu,memory=line.split()
        samples.append({'nominal_s':int(n)*5,'router_cpu_percent':float(cpu),'container_cpu_percent':float(container_cpu)/10,'memory_bytes':int(memory)})
    wait_for(lambda:'DONE' in client('cat '+output)['out'],100)
    transfers=[]
    for line in client('cat '+output)['out'].splitlines():
        if line=='DONE':continue
        name,rc,http,size,elapsed=line.split()
        transfers.append({'name':name,'exit':int(rc),'http':int(http),'bytes':int(float(size)),'seconds':float(elapsed)})
    assert len(transfers)==2 and all(x['exit']==0 and x['http']==206 and x['bytes']==2097152 for x in transfers),transfers
    wait_for(m.ready,180)
    return {'detached_client':True,'streams':transfers,'rate_limit_per_stream_bytes_s':32768,'resource_samples':samples,
            'scope':'paced transfer under free-CHR bandwidth cap; not a throughput benchmark'}

def continuity():
    samples=[];started=time.monotonic()
    with ThreadPoolExecutor(max_workers=4) as pool:
        for index in range(30):
            jobs={
              'github':"curl --noproxy '*' -4 -fsS --connect-timeout 4 --max-time 10 --resolve github.com:443:140.82.112.4 https://github.com/robots.txt -o /dev/null -w '%{http_code}'",
              'google':"curl --noproxy '*' -4 -fsS --connect-timeout 4 --max-time 10 https://www.gstatic.com/generate_204 -o /dev/null -w '%{http_code}'",
              'warp':"curl --noproxy '*' -4 -fsS --connect-timeout 4 --max-time 10 https://cloudflare.com/cdn-cgi/trace | grep '^warp='",
              'dns':"nslookup -type=A example.com 9.9.9.9 >/dev/null"}
            futures={name:pool.submit(client,command) for name,command in jobs.items()}
            results={name:f.result() for name,f in futures.items()}
            # Keep DNS output and egress IP addresses out of the public report.
            row={'round':index+1,'elapsed_s':round(time.monotonic()-started,1),
                 'github_200':results['github']['exit']==0 and results['github']['out']=='200',
                 'google_204':results['google']['exit']==0 and results['google']['out']=='204',
                 'warp_on':results['warp']['exit']==0 and results['warp']['out']=='warp=on',
                 'udp_dns':results['dns']['exit']==0,'ready':m.ready()}
            samples.append(row);report['continuity_samples']=samples;save()
            if index<29:time.sleep(6)
    counts={key:sum(row[key] for row in samples) for key in ('github_200','google_204','warp_on','udp_dns','ready')}
    # Preserve observed failures instead of silently retrying individual samples.
    return {'rounds':30,'seconds':round(time.monotonic()-started,1),'successful_samples':counts,
            'all_checks_passed_rounds':sum(all(row[key] for key in counts) for row in samples)}

try:
    assert not m.pending() and m.record('installed')['image_id']==bundle['image_id']
    wait_for(m.ready,420)
    case('final image normal router reboot',reboot)
    case('two detached paced non-Cloudflare downloads',paced_load)
    case('bounded client continuity observation',continuity)
    report['final_status']=shell('/usr/local/sbin/mikrowarp',check=False)
    report['routeros']=m.rows('/system/resource')[0]['version']
finally:
    report['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat();save()
