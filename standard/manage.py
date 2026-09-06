#!/usr/bin/env python3
"""Explicit admin operations. Never installs traffic-selection or health scripts."""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import uuid
from router import Router, quote

NAME='mikrowarp'
BRIDGE='mikrowarp-link'
VETH='mikrowarp-veth'

def digest(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()

def wait_for(fn, seconds=360):
    start=time.monotonic()
    while True:
        value=fn()
        if value: return value
        if time.monotonic()-start>seconds: raise TimeoutError('Timed out; rerun the same operation to resume')
        time.sleep(3)

class Manager:
    def __init__(self, profile):
        self.p=profile; self.r=Router(profile)
        self.base=profile['directory'].strip('/')
        if not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*',self.base):
            raise ValueError('Use a simple dedicated directory, without dots or spaces')
        self.owner=profile['owner']
        if not re.fullmatch('[0-9a-f]{32}',self.owner): raise ValueError('Profile needs its persistent random owner ID')
        self.net=ipaddress.IPv4Network(profile['network'])
        private_ranges=[ipaddress.IPv4Network(cidr) for cidr in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')]
        if self.net.prefixlen!=30 or not any(self.net.subnet_of(network) for network in private_ranges):
            raise ValueError('Use an RFC1918 /30 transit network')
        self.router_ip=str(self.net[1]); self.gateway=str(self.net[2]); self.wan=profile['wan']
        self.prefix='MikroWARP | '

    def comment(self,purpose): return self.prefix+purpose+' ['+self.owner+']'

    def rows(self,menu,condition=''): return self.r.rows(menu,condition)

    def file_exists(self,path): return bool(self.rows('/file','name='+quote(path)))

    def mkdir(self,path):
        parts=path.split('/')
        for i in range(1,len(parts)+1):
            part='/'.join(parts[:i])
            rows=self.rows('/file','name='+quote(part))
            if not rows: self.r.run('/file/add name='+quote(part)+' type=directory')
            elif rows[0]['type'] not in ('directory','disk'): raise RuntimeError('Directory path is occupied: '+part)

    def read(self,path):
        if not self.file_exists(path): return None
        return self.r.run(':put [/file/get [find where name='+quote(path)+'] contents]')

    def write(self,path,value):
        if self.file_exists(path):
            self.r.run('/file/set [find where name='+quote(path)+'] contents='+quote(value))
        else: self.r.run('/file/add name='+quote(path)+' type=file contents='+quote(value))

    def ensure(self,menu,selector,properties):
        found=self.rows(menu,selector)
        if len(found)>1: raise RuntimeError('Ambiguous object in '+menu)
        if found:
            for key,value in properties.items():
                actual=found[0].get(key)
                if isinstance(actual,bool): actual='yes' if actual else 'no'
                if isinstance(actual,list): actual=','.join(str(x) for x in actual)
                if key in ('src','dst') and actual is not None:
                    actual=str(actual).lstrip('/'); value=str(value).lstrip('/')
                if key in ('src-address','dst-address') and actual:
                    actual=str(ipaddress.IPv4Network(actual,strict=False))
                if str(actual)!=str(value):
                    raise RuntimeError('Existing object differs: '+menu+' '+key+'; inspect it before resuming')
            return found[0]
        self.r.run(menu+'/add '+' '.join(key+'='+quote(value) for key,value in properties.items()))
        return self.rows(menu,selector)[0]

    def preflight(self,bundle=None):
        if bundle:
            if not re.fullmatch('sha256:[0-9a-f]{64}',bundle.get('image_id','')) or not re.fullmatch('[0-9a-f]{64}',bundle.get('sha256','')):
                raise ValueError('Bundle must contain SHA-256 image and archive identifiers')
            if bundle.get('architecture')!='amd64': raise ValueError('Bundle is not amd64')
            for field in ('logical_bytes','archive_bytes'):
                if type(bundle.get(field)) is not int or not 0<bundle[field]<2**31: raise ValueError('Invalid bundle size')
        resource=self.rows('/system/resource')[0]
        if resource['architecture-name']!='x86_64': raise RuntimeError('Standard currently targets x86-64 CHR')
        if not str(resource['version']).startswith('7.23.'):
            raise RuntimeError('This candidate installer supports RouterOS 7.23.x; no router upgrade is performed')
        if not self.rows('/system/package','name="container"'): raise RuntimeError('Install the matching RouterOS container package first')
        if self.rows('/system/device-mode')[0].get('container') is not True:
            raise RuntimeError('Container device mode must already be enabled')
        if not self.rows('/interface','name='+quote(self.wan)): raise RuntimeError('Configured uplink interface does not exist')
        owner=self.read(self.base+'/owner.txt')
        if self.file_exists(self.base) and owner!=self.owner:
            children=[row for row in self.rows('/file') if row['name'].startswith(self.base+'/')]
            if owner is not None or children: raise RuntimeError('Storage directory is not owned by this installation')
        for row in self.rows('/ip/address'):
            if row.get('comment')==self.comment('Transit address'): continue
            if ipaddress.IPv4Interface(row['address']).network.overlaps(self.net):
                raise RuntimeError('Transit subnet overlaps an existing router address')
        for name in (BRIDGE,VETH):
            for row in self.rows('/interface','name='+quote(name)):
                if self.owner not in row.get('comment',''): raise RuntimeError('Interface name is already in use: '+name)
        for row in self.rows('/container','name='+quote(NAME)):
            if self.owner not in row.get('comment',''): raise RuntimeError('Container name is already in use')
        free=int(resource['free-hdd-space'])
        for disk in self.rows('/disk'):
            mount=disk.get('mount-point','')
            if mount and (self.base==mount or self.base.startswith(mount+'/')): free=int(disk['free'])
        if bundle:
            need=bundle['archive_bytes']+2*bundle['logical_bytes']+256*1024*1024
            if free<need: raise RuntimeError(f'Insufficient staging space: need {need} free bytes; found {free}')
        return {'router':resource['version'],'gateway':self.gateway,'directory':self.base,'free_bytes':free}

    def network(self):
        self.ensure('/interface/bridge','name='+quote(BRIDGE),{'name':BRIDGE,'protocol-mode':'none','comment':self.comment('Transit link')})
        self.ensure('/interface/veth','name='+quote(VETH),{'name':VETH,'address':self.gateway+'/30','gateway':self.router_ip,'comment':self.comment('Gateway')})
        self.ensure('/interface/bridge/port','interface='+quote(VETH),{'bridge':BRIDGE,'interface':VETH,'comment':self.comment('Gateway port')})
        self.ensure('/ip/address','comment='+quote(self.comment('Transit address')),{'address':self.router_ip+'/30','interface':BRIDGE,'comment':self.comment('Transit address')})
        rules=[('/ip/firewall/nat','Uplink NAT',{'chain':'srcnat','src-address':self.gateway+'/32','out-interface':self.wan,'action':'masquerade'}),
          ('/ip/firewall/filter','Protect router services',{'chain':'input','in-interface':BRIDGE,'connection-state':'invalid,new,untracked','action':'drop'}),
          ('/ip/firewall/filter','Allow container uplink',{'chain':'forward','in-interface':BRIDGE,'src-address':self.gateway+'/32','out-interface':self.wan,'action':'accept'}),
          ('/ip/firewall/filter','Block container initiated LAN access',{'chain':'forward','in-interface':BRIDGE,'connection-state':'invalid,new,untracked','action':'drop'})]
        ordered={}
        for menu,purpose,properties in rules:
            properties['comment']=self.comment(purpose)
            row=self.ensure(menu,'comment='+quote(properties['comment']),properties)
            ordered.setdefault(menu,[]).append(row['.id'])
        # Leave an already-correct configuration untouched when resuming.
        for menu,ids in ordered.items():
            if [row['.id'] for row in self.rows(menu)][:len(ids)]!=ids:
                for item in reversed(ids):
                    if self.rows(menu)[0]['.id']!=item:self.r.run(menu+'/move '+quote(item)+' destination=0')
        self.ensure('/container/envs','list="mikrowarp" and key="MIKROWARP_STATE_ID"',
                    {'list':NAME,'key':'MIKROWARP_STATE_ID','value':self.owner})
        self.ensure('/container/mounts','list="mikrowarp"',{'list':NAME,'src':self.base+'/data','dst':'/var/lib/mikrowarp'})

    def transfer(self,archive,bundle):
        if digest(archive)!=bundle['sha256'] or Path(archive).stat().st_size!=bundle['archive_bytes']:
            raise RuntimeError('Local bundle checksum or size differs')
        path=self.archive_path(bundle)
        self.mkdir(self.base+'/archives')
        if not self.file_exists(path):
            partial=path+'.'+uuid.uuid4().hex+'.upload'
            try:
                self.r.copy(str(archive),partial)
                if int(self.rows('/file','name='+quote(partial))[0]['size'])!=bundle['archive_bytes']:
                    raise RuntimeError('Uploaded image size differs')
                self.r.run('/file/set [find where name='+quote(partial)+'] name='+quote(path))
            except BaseException:
                try:self.r.run('/file/remove [find where name='+quote(partial)+']')
                except Exception:pass
                raise
        # SSH authenticates transfer integrity. Import additionally checks the
        # gzip archive; verify the image ID and retained binaries after extraction.
        # Downloading the whole archive back is prohibitively slow on free CHR.
        row=self.rows('/file','name='+quote(path))[0]
        if int(row['size'])!=bundle['archive_bytes']: raise RuntimeError('Uploaded image size differs; retry the incomplete transfer')
        return path

    def archive_path(self,bundle): return self.base+'/archives/'+bundle['sha256']+'.tar.gz'

    def container(self,name=NAME):
        rows=self.rows('/container','name='+quote(name))
        if len(rows)>1: raise RuntimeError('Container name is ambiguous')
        if rows and not rows[0].get('downloading/extracting'):
            rows[0]['image-id']=self.r.run(':put [/container/get '+quote(rows[0]['.id'])+' image-id]')
        return rows[0] if rows else None

    def import_image(self,archive,bundle,name=NAME):
        row=self.container(name)
        if not row:
            release=self.base+'/releases/'+bundle['image_id'].removeprefix('sha256:')[:16]
            self.mkdir(release)
            self.r.run('/container/add name='+quote(name)+' file='+quote(archive)+' interface='+quote(VETH)+
                ' root-dir='+quote(release+'/root')+' layer-dir='+quote(release+'/layers')+
                ' envlists=mikrowarp mountlists=mikrowarp dns=1.1.1.1 user=0:0 logging=yes start-on-boot=no'+
                ' restart-policy=always restart-interval=10s comment='+quote(self.comment('Standard '+bundle['image_id'][7:19])))
        expected=bundle['image_id'].removeprefix('sha256:')
        def extracted():
            row=self.container(name)
            if row.get('error') or row.get('failed'): raise RuntimeError('Image extraction failed; existing state is retained')
            if row.get('extracting') or row.get('downloading') or row.get('downloading/extracting'): return False
            if str(row.get('image-id','')).removeprefix('sha256:')!=expected: raise RuntimeError('Imported image ID differs from the verified bundle')
            return row
        return wait_for(extracted)

    def ready(self,name=NAME):
        try: return self.r.shell(name,'/usr/local/sbin/mikrowarp',check=False)[0]==0
        except (RuntimeError,TimeoutError): return False

    def install(self,archive,bundle):
        self.preflight(bundle)
        existing=self.container()
        if existing and not existing.get('downloading/extracting') and existing.get('image-id')!=bundle['image_id'][7:]:
            raise RuntimeError('A different image is installed; use update')
        if digest(archive)!=bundle['sha256']: raise RuntimeError('Local archive checksum mismatch')
        self.mkdir(self.base)
        if self.read(self.base+'/owner.txt') is None: self.write(self.base+'/owner.txt',self.owner)
        self.mkdir(self.base+'/data'); self.write(self.base+'/data/owner.txt',self.owner)
        for name in ('state','logs','diagnostics'): self.mkdir(self.base+'/data/'+name)
        self.network()
        print('Owned transit and uplink objects ready; uploading/verifying image.',flush=True)
        path=self.transfer(archive,bundle)
        row=self.import_image(path,bundle)
        if self.r.run(':put [/container/get '+quote(row['.id'])+' start-on-boot]')!='true':
            if not row.get('stopped'):
                self.r.run('/container/stop '+quote(row['.id']))
                wait_for(lambda:self.container().get('stopped'),60)
            self.r.run('/container/set '+quote(row['.id'])+' start-on-boot=yes')
            row=self.container()
        if row.get('stopped'): self.r.run('/container/start '+quote(row['.id']))
        self.write(self.base+'/installed.json',json.dumps(bundle,separators=(',',':')))
        print('Installed; waiting for fresh forwarded WARP health.',flush=True)
        wait_for(self.ready,420)
        self.r.shell(NAME,'cd /; sha256sum -c /usr/share/mikrowarp/warp-binaries.sha256')
        print('Ready. Gateway '+self.gateway+'. Administrator routing policy is unchanged.',flush=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['plan','install','status','update','rollback','resume','abort'])
    parser.add_argument('--profile',type=Path,required=True)
    parser.add_argument('--bundle',type=Path)
    parser.add_argument('--archive',type=Path)
    args=parser.parse_args()
    from lifecycle import Lifecycle
    manager=Lifecycle(json.loads(args.profile.read_text()))
    bundle=json.loads(args.bundle.read_text()) if args.bundle else None
    if args.action=='plan': print(json.dumps(manager.preflight(bundle),indent=2)); return
    if args.action=='status': print(manager.r.shell(NAME,'/usr/local/sbin/mikrowarp',check=False)[1]); return
    if args.action in ('install','update') and (not bundle or not args.archive): parser.error('This operation requires --bundle and --archive')
    def terminate(signum,frame): raise KeyboardInterrupt('Administrator operation interrupted')
    signal.signal(signal.SIGTERM,terminate)
    manager.r.claim()
    try:
        if args.action=='install':manager.install(args.archive,bundle)
        elif args.action=='update':manager.begin_update(args.archive,bundle)
        elif args.action=='rollback':manager.begin_rollback()
        elif args.action=='resume':manager.resume()
        else:manager.abort()
    finally:manager.r.release()

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:
        print('Interrupted. Rerun install, or use resume/abort for a pending update.',file=sys.stderr)
        raise SystemExit(130)
    except (RuntimeError,TimeoutError,ValueError,OSError,subprocess.SubprocessError) as exc:
        print('Error: '+str(exc),file=sys.stderr)
        raise SystemExit(1)
