#!/usr/bin/env python3
"""Fault checks restricted to two explicitly named disposable Docker containers."""
import datetime
import json
from pathlib import Path
import subprocess
import time

GATEWAY='mikrowarp-r14-native'
CLIENT='mikrowarp-r14-native-client'
OUT=Path(__file__).resolve().parents[2]/'runtime/standard-r14'

def call(args,timeout=35):
    r=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    return {'code':r.returncode,'out':r.stdout.strip(),'error':r.stderr.strip()}

def gateway(command): return call(['docker','exec',GATEWAY,'bash','-c',command])
def client(command): return call(['docker','exec',CLIENT,'bash','-c',command])

def ping():
    return call(['docker','run','--rm','--network','container:'+CLIENT,'alpine:3.22',
                 'ping','-c','1','-W','2','172.30.114.2'],10)['code']==0

def ready(): return gateway('/usr/local/sbin/mikrowarp')['code']==0

def wait_ready():
    until=time.monotonic()+240
    while time.monotonic()<until:
        if ready(): return
        time.sleep(3)
    raise TimeoutError('Native WARP did not become ready')

def freeze():
    wait_ready()
    assert ping(),'Healthy gateway did not answer ICMP'
    baseline=client('curl -4 -sS --max-time 10 https://www.google.com/generate_204 -o /dev/null -w "%{http_code}"')
    assert baseline['code']==0 and baseline['out']=='204',baseline
    result={'test':'controller freeze','utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'healthy_ping':True,'baseline_google':baseline,'status':'incomplete'}
    try:
        assert call(['docker','kill','--signal','STOP',GATEWAY])['code']==0
        started=time.monotonic()
        time.sleep(30)
        result['service_survives_30s']=gateway('warp-cli --accept-tos status')
        time.sleep(35)
        result['elapsed_s']=round(time.monotonic()-started,2)
        result['expired_status']=gateway('/usr/local/sbin/mikrowarp')
        result['expired_ping']=ping()
        result['expired_google']=client('curl -4 -sS --connect-timeout 3 --max-time 5 https://www.google.com/generate_204 -o /dev/null -w "%{http_code}"')
        result['arp_neighbor']=client('ip neigh show 172.30.114.2')
        assert result['expired_status']['code']!=0
        assert not result['expired_ping']
        assert result['expired_google']['code']!=0
        assert 'lladdr' in result['arp_neighbor']['out']
        result['status']='pass'
    finally:
        call(['docker','kill','--signal','CONT',GATEWAY])
        (OUT/'native-controller-freeze.json').write_text(json.dumps(result,indent=2)+'\n')
    wait_ready(); assert ping()
    result['recovered']=True
    (OUT/'native-controller-freeze.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__': freeze()
