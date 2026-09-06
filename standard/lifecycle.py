"""Manual staged updates. Normal operation leaves exactly one container object."""
import hashlib
import json
import uuid
from manage import Manager, NAME, wait_for
from router import quote

NEXT='mikrowarp-next'
OLD='mikrowarp-old'

def packed(value): return json.dumps(value,sort_keys=True,separators=(',',':'))

class Lifecycle(Manager):
    def record(self,name):
        value=self.read(self.base+'/'+name+'.json')
        return json.loads(value) if value else None

    def journal(self):
        valid=[]
        for slot in (0,1):
            text=self.read(self.base+'/operation.'+str(slot)+'.json')
            if not text: continue
            try:
                row=json.loads(text)
                if hashlib.sha256(packed(row['payload']).encode()).hexdigest()==row['sha256']:
                    valid.append(row['payload'])
            except (ValueError,KeyError,TypeError): pass
        return max(valid,key=lambda row:row['sequence']) if valid else None

    def save_job(self,job,phase):
        current=self.journal(); job=dict(job)
        job['sequence']=(current or {}).get('sequence',0)+1;job['phase']=phase
        text=packed({'payload':job,'sha256':hashlib.sha256(packed(job).encode()).hexdigest()})
        path=self.base+'/operation.'+str(job['sequence']%2)+'.json'
        self.write(path,text)
        if self.read(path)!=text: raise RuntimeError('Operation journal readback failed')
        return job

    def checked(self,name,bundle):
        row=self.container(name)
        if not row: return None
        if self.owner not in row.get('comment',''): raise RuntimeError('Unowned lifecycle container: '+name)
        if row.get('downloading/extracting'): return row
        if row['image-id']!=bundle['image_id'].removeprefix('sha256:'):
            raise RuntimeError('Unexpected image in lifecycle container: '+name)
        return row

    def start(self,name,bundle,boot=True):
        row=self.checked(name,bundle)
        if not row: raise RuntimeError('Missing container: '+name)
        current=self.r.run(':put [/container/get '+quote(row['.id'])+' start-on-boot]')=='true'
        if current!=boot:
            # RouterOS may restart a running container even for a repeated set.
            if not row.get('stopped'):
                self.r.run('/container/stop '+quote(row['.id']))
                wait_for(lambda:self.checked(name,bundle).get('stopped'),60)
            self.r.run('/container/set '+quote(row['.id'])+' start-on-boot='+('yes' if boot else 'no'))
            row=self.checked(name,bundle)
        if row.get('stopped'): self.r.run('/container/start '+quote(row['.id']))
        def shell_available():
            try: return self.r.shell(name,'test -r /run/mikrowarp/runtime.env',check=False)[0]==0
            except RuntimeError: return False
        wait_for(shell_available,90)

    def stop(self,name,bundle):
        row=self.checked(name,bundle)
        if not row: return
        if not row.get('stopped'): self.r.run('/container/stop '+quote(row['.id']))
        wait_for(lambda:self.checked(name,bundle).get('stopped'),60)
        if self.r.run(':put [/container/get '+quote(row['.id'])+' start-on-boot]')=='true':
            self.r.run('/container/set '+quote(row['.id'])+' start-on-boot=no')

    def rename(self,source,target,bundle):
        if self.container(target): raise RuntimeError('Rename target already exists: '+target)
        row=self.checked(source,bundle)
        if not row or not row.get('stopped'): raise RuntimeError('Rename requires a stopped owned container')
        self.r.run('/container/set '+quote(row['.id'])+' name='+quote(target))
        self.checked(target,bundle)

    def remove(self,name,bundle):
        row=self.checked(name,bundle)
        if not row: return
        if not row.get('stopped'): raise RuntimeError('Refusing to remove a running container')
        self.r.run('/container/remove '+quote(row['.id']))
        wait_for(lambda:not self.rows('/container','name='+quote(name)),180)

    def pending(self):
        job=self.journal()
        return job if job and job['phase'] not in ('complete','aborted') else None

    def begin_update(self,archive,bundle):
        if self.pending(): raise RuntimeError('An operation is pending; use resume or abort')
        self.preflight(bundle)
        old=self.record('installed')
        if not old: raise RuntimeError('Installation record is missing')
        self.checked(NAME,old)
        if old['image_id']==bundle['image_id']: raise RuntimeError('This exact image is already installed')
        if not self.file_exists(self.archive_path(old)): raise RuntimeError('Current image archive is missing; restore it before updating')
        if self.container(NEXT) or self.container(OLD): raise RuntimeError('A lifecycle container name is already occupied')
        self.transfer(archive,bundle)
        job={'kind':'update','old':old,'new':bundle,'snapshot':hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
             'restore_snapshot':None,'former_previous':self.record('previous')}
        self.save_job(job,'staging'); self.resume()

    def begin_rollback(self):
        if self.pending(): raise RuntimeError('An operation is pending; use resume or abort')
        previous=self.record('previous'); old=self.record('installed')
        if not previous: raise RuntimeError('No accepted previous release is available')
        self.preflight(previous['bundle']);self.checked(NAME,old)
        if self.container(NEXT) or self.container(OLD): raise RuntimeError('A lifecycle container name is already occupied')
        job={'kind':'rollback','old':old,'new':previous['bundle'],
             'snapshot':hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
             'restore_snapshot':previous['snapshot'],'former_previous':previous}
        self.save_job(job,'staging'); self.resume()

    def resume(self):
        self.preflight()
        job=self.pending()
        if not job: print('No pending operation.'); return
        if job['phase']=='aborting': self.abort(); return
        if job['phase']=='committing': self.commit(job); return
        old,new=job['old'],job['new']
        current=self.container(NAME)
        if current and current.get('image-id')==old['image_id'][7:]:
            self.checked(NAME,old)
            path=self.archive_path(new)
            if not self.file_exists(path): raise RuntimeError('Staged image archive is missing')
            self.import_image(path,new,NEXT)
            job=self.save_job(job,'quiescing')
            self.start(NAME,old)
            self.r.shell(NAME,'/usr/local/sbin/mikrowarp maintenance begin',timeout=60)
            self.r.shell(NAME,'/usr/local/sbin/mikrowarp maintenance snapshot '+job['snapshot'],timeout=120)
            job['snapshot_created']=True
            job=self.save_job(job,'switching')
            self.stop(NAME,old);self.rename(NAME,OLD,old)
        if not self.container(NAME):
            if not self.checked(OLD,old) or not self.checked(NEXT,new): raise RuntimeError('Interrupted switch is missing a required container')
            self.rename(NEXT,NAME,new)
        self.checked(NAME,new)
        try:
            self.start(NAME,new)
            if job['restore_snapshot'] and job['phase'] in ('staging','quiescing','switching'):
                self.r.shell(NAME,'/usr/local/sbin/mikrowarp maintenance begin',timeout=60)
                self.r.shell(NAME,'/usr/local/sbin/mikrowarp maintenance restore '+job['restore_snapshot'],timeout=120)
            job=self.save_job(job,'validating')
            self.r.shell(NAME,'/usr/local/sbin/mikrowarp maintenance resume')
            print('Candidate running; validating fresh WARP forwarding.',flush=True)
            wait_for(self.ready,420)
            self.r.shell(NAME,'cd /; sha256sum -c /usr/share/mikrowarp/warp-binaries.sha256')
        except (RuntimeError,TimeoutError) as exc:
            print('Candidate did not pass. Restoring the previous image and state.',flush=True)
            self.abort()
            raise RuntimeError('Candidate rejected; the previous image and state were restored. Cause: '+str(exc)) from exc
        job=self.save_job(job,'committing')
        self.commit(job)

    def commit(self,job):
        old,new=job['old'],job['new']
        self.checked(NAME,new)
        self.write(self.base+'/previous.json',packed({'bundle':old,'snapshot':job['snapshot']}))
        self.write(self.base+'/installed.json',packed(new))
        self.remove(OLD,old)
        self.prune(job)
        self.save_job(job,'complete')
        print('Operation complete. One running container; previous image and matching state retained.',flush=True)

    def abort(self):
        self.preflight();job=self.pending()
        if not job: print('No pending operation.'); return
        if job['phase']=='committing': raise RuntimeError('Commit already began; use resume to finish it')
        old,new=job['old'],job['new'];self.save_job(job,'aborting')
        current=self.container(NAME)
        # Hold startup before any old binary can see candidate-mutated state.
        if job.get('snapshot_created'):
            self.write(self.base+'/data/maintenance.lock','administrator_operation')
        if current and current.get('image-id')==new['image_id'][7:]:
            self.stop(NAME,new); self.remove(NAME,new)
        if not self.container(NAME):
            if self.container(OLD): self.rename(OLD,NAME,old)
            else: self.import_image(self.archive_path(old),old,NAME)
        self.start(NAME,old)
        if job.get('snapshot_created'):
            self.r.shell(NAME,'/usr/local/sbin/mikrowarp maintenance begin',timeout=60)
            self.r.shell(NAME,'/usr/local/sbin/mikrowarp maintenance restore '+job['snapshot'],timeout=120)
        self.r.shell(NAME,'/usr/local/sbin/mikrowarp maintenance resume')
        if self.container(NEXT):
            self.import_image(self.archive_path(new),new,NEXT)
            self.stop(NEXT,new);self.remove(NEXT,new)
        self.write(self.base+'/installed.json',packed(old))
        kept={old['sha256']}
        if job.get('former_previous'):kept.add(job['former_previous']['bundle']['sha256'])
        if new['sha256'] not in kept:
            self.r.run('/file/remove [find where name='+quote(self.archive_path(new))+']')
        if job.get('snapshot_created'):
            self.r.shell(NAME,'rm -f /var/lib/mikrowarp/recovery/'+job['snapshot']+'.tar /var/lib/mikrowarp/recovery/'+job['snapshot']+'.tar.sha256')
        self.save_job(job,'aborted')
        print('Previous image and state restored; waiting for connectivity.',flush=True)
        wait_for(self.ready,420)

    def prune(self,job):
        # Remove only the explicitly recorded obsolete release, never by prefix.
        former=job.get('former_previous')
        if not former: return
        kept={job['old']['sha256'],job['new']['sha256']}
        if former['bundle']['sha256'] not in kept:
            path=self.archive_path(former['bundle'])
            self.r.run('/file/remove [find where name='+quote(path)+']')
        if former['snapshot']!=job['snapshot']:
            # Runtime paths are fixed and the label is a generated SHA-256 token.
            label=former['snapshot']
            if len(label)!=64 or any(c not in '0123456789abcdef' for c in label): raise RuntimeError('Invalid recorded snapshot label')
            self.r.shell(NAME,'rm -f /var/lib/mikrowarp/recovery/'+label+'.tar /var/lib/mikrowarp/recovery/'+label+'.tar.sha256')
