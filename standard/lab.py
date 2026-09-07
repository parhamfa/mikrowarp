#!/usr/bin/env python3
"""Dedicated loopback-only QEMU lab. No production SSH aliases are accepted."""
import argparse
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'runtime/standard-r14'
ROUTER_PORT = 23222
CLIENT_PORT = 23022
LAN_PORT = 13000
WINBOX_PORT = 29291

def prepare():
    OUT.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(OUT, 0o700)
    for name in ('chr', 'appdisk'):
        target = OUT / (name + '.qcow2')
        if not target.exists():
            subprocess.run(['qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2',
                            '-b', str(ROOT / 'runtime' / (name + '.qcow2')), str(target)], check=True)
    key = OUT / 'key'
    if not key.exists():
        # Keep the existing lab login on the clone through the initial reset.
        shutil.copy2(ROOT / 'runtime/ssh/lab_key', key)
        os.chmod(key, 0o600)
    return OUT

def running(kind):
    pidfile = OUT / (kind + '.pid')
    if not pidfile.exists(): return False
    pid = int(pidfile.read_text())
    found = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, text=True).stdout
    return 'qemu-system-x86_64' in found and str(OUT) in found and 'mikrowarp-r14-' + kind in found

def start(kind):
    prepare()
    if running(kind): return
    for suffix in ('serial','qmp','pid'):
        (OUT / (kind + '.' + suffix)).unlink(missing_ok=True)
    args = ['qemu-system-x86_64', '-name', 'mikrowarp-r14-' + kind,
            '-machine', 'pc,accel=tcg', '-cpu', 'max', '-smp', '2' if kind=='router' else '1',
            '-m', '1536' if kind=='router' else '384', '-display', 'none', '-daemonize',
            '-pidfile', str(OUT / (kind+'.pid')),
            '-qmp', 'unix:'+str(OUT/(kind+'.qmp'))+',server=on,wait=off',
            '-chardev', 'socket,id=serial,path='+str(OUT/(kind+'.serial'))+
            ',server=on,wait=off,logfile='+str(OUT/(kind+'.console-private.log'))+',logappend=on',
            '-serial', 'chardev:serial']
    if kind == 'router':
        args += ['-drive','file='+str(OUT/'chr.qcow2')+',format=qcow2,if=virtio',
                 '-drive','file='+str(OUT/'appdisk.qcow2')+',format=qcow2,if=virtio',
                 '-device','virtio-net-pci,netdev=wan,mac=52:54:00:10:00:01',
                 '-netdev','user,id=wan,net=10.0.2.0/24,dhcpstart=10.0.2.15,'+
                 f'hostfwd=tcp:127.0.0.1:{ROUTER_PORT}-:22,hostfwd=tcp:127.0.0.1:{WINBOX_PORT}-:8291',
                 '-device','virtio-net-pci,netdev=lan,mac=52:54:00:10:00:02',
                 '-netdev',f'socket,id=lan,listen=127.0.0.1:{LAN_PORT}']
    else:
        iso=ROOT/'runtime/downloads/alpine-virt-3.22.1-x86_64.iso'
        boot=OUT/'alpine-boot';boot.mkdir(exist_ok=True)
        subprocess.run(['bsdtar','-xf',str(iso),'-C',str(boot),'boot/vmlinuz-virt','boot/initramfs-virt'],check=True)
        shared=ROOT/'runtime/client-shared'
        args += ['-cdrom',str(iso),'-kernel',str(boot/'boot/vmlinuz-virt'),
                 '-initrd',str(boot/'boot/initramfs-virt'),
                 '-append','console=ttyS0,115200 modules=loop,squashfs,sd-mod,usb-storage quiet',
                 '-device','virtio-net-pci,netdev=lan,mac=52:54:00:20:00:10',
                 '-netdev',f'socket,id=lan,connect=127.0.0.1:{LAN_PORT}',
                 '-device','virtio-net-pci,netdev=management,mac=52:54:00:20:00:11',
                 '-netdev',f'user,id=management,net=10.77.0.0/24,restrict=on,hostfwd=tcp:127.0.0.1:{CLIENT_PORT}-10.77.0.15:22',
                 '-virtfs','local,path='+str(shared)+',mount_tag=lab,security_model=none,readonly=on']
    subprocess.run(args,check=True)

def qmp(kind, command, arguments=None):
    assert kind in ('router','client') and running(kind)
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(10);s.connect(str(OUT/(kind+'.qmp')))
        f=s.makefile('rwb',buffering=0);json.loads(f.readline())
        for n,request in enumerate([{'execute':'qmp_capabilities'}, {'execute':command,'arguments':arguments or {}}]):
            request['id']=n;f.write((json.dumps(request)+'\n').encode())
            while True:
                reply=json.loads(f.readline())
                if reply.get('id')==n:
                    if 'error' in reply: raise RuntimeError(reply['error'])
                    break
        return reply

def serial(kind, text='', seconds=3):
    assert kind in ('router','client') and running(kind)
    data=b''
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(str(OUT/(kind+'.serial')))
        if text: s.sendall(text.encode())
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            if select.select([s],[],[],min(0.5,until-time.monotonic()))[0]:
                block=s.recv(65536)
                if not block:break
                data+=block
    return data.decode(errors='replace')

def ssh_args(kind, scp=False):
    assert kind in ('router','client')
    return (['scp','-O','-q','-P'] if scp else ['ssh','-p']) + [str(ROUTER_PORT if kind=='router' else CLIENT_PORT),
        '-F','/dev/null','-i',str(OUT/'key'),'-o','IdentitiesOnly=yes','-o','BatchMode=yes',
        '-o','ConnectTimeout=5','-o','StrictHostKeyChecking=accept-new',
        '-o','UserKnownHostsFile='+str(OUT/'known_hosts'),'-o','LogLevel=ERROR']

def ssh(kind, command, timeout=30):
    return subprocess.run(ssh_args(kind)+[('admin' if kind=='router' else 'root')+'@127.0.0.1',command],
                          capture_output=True,text=True,timeout=timeout)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','start','serial','ssh','poweroff','reset','wan-down','wan-up'])
    p.add_argument('kind',nargs='?',default='router',choices=['router','client']);p.add_argument('text',nargs='?',default='')
    a=p.parse_args()
    if a.action=='prepare':print(prepare())
    elif a.action=='start':start(a.kind);print('Started local '+a.kind)
    elif a.action=='serial':print(serial(a.kind,a.text))
    elif a.action=='ssh':
        r=ssh(a.kind,a.text);print(r.stdout,end='');print(r.stderr,end='');raise SystemExit(r.returncode)
    elif a.action=='poweroff':print(qmp(a.kind,'quit'))
    elif a.action=='reset':print(qmp(a.kind,'system_reset'))
    else:print(qmp('router','set_link',{'name':'wan','up':a.action=='wan-up'}))
