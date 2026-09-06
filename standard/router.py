"""Explicit SSH transport for the admin tool; the lab profile is loopback-only."""
import json
import re
import subprocess
import uuid

def quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('\n', '\\n') + '"'

class Router:
    def __init__(self, profile):
        self.lock_token=None
        self.profile = profile
        self.host = profile['host']
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', self.host) or self.host.startswith('-'):
            raise ValueError('Use an explicit host name or IPv4 address')
        self.user = profile.get('user', 'admin')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', self.user): raise ValueError('Invalid SSH user')
        self.options = ['-F', '/dev/null', '-i', profile['key'], '-o', 'IdentitiesOnly=yes',
            '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=8',
            '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
            '-o', 'UserKnownHostsFile='+profile['known_hosts'], '-o', 'LogLevel=ERROR']

    def run(self, command, timeout=60, shell_marker=False):
        guard = ':if ([/system/identity get name] != '+quote(self.profile['identity'])+') do={ :error "Router identity mismatch" }; '
        if self.lock_token:
            guard+=':global mikrowarpAdminLock; :global mikrowarpAdminUntil; :if (($mikrowarpAdminLock != '+quote(self.lock_token)+') || ([:typeof $mikrowarpAdminUntil] != "time") || ($mikrowarpAdminUntil < [:timestamp])) do={ :error "Administrator operation lease expired" }; :set mikrowarpAdminUntil ([:timestamp]+10m); '
        text = ':onerror e in={ '+guard+command+'; :put "__MW_OK__" } do={ :put ("__MW_ERROR__".$e) }'
        result = subprocess.run(['ssh', '-p', str(self.profile.get('port', 22))]+self.options+
            [self.user+'@'+self.host, text], capture_output=True, text=True, timeout=timeout)
        completed='__MW_OK__' in result.stdout or (shell_marker and '__MW_EXIT=' in result.stdout)
        if result.returncode or not completed or '__MW_ERROR__' in result.stdout:
            raise RuntimeError((result.stdout+result.stderr).strip())
        return result.stdout.replace('__MW_OK__', '').strip()

    def claim(self):
        token=uuid.uuid4().hex
        self.run(':global mikrowarpAdminLock; :global mikrowarpAdminUntil; :if (([:typeof $mikrowarpAdminUntil] = "time") && ($mikrowarpAdminUntil > [:timestamp])) do={ :error "Another administrator operation holds the lease; retry after it finishes or the ten-minute lease expires" }; :set mikrowarpAdminLock '+quote(token)+'; :set mikrowarpAdminUntil ([:timestamp]+10m)')
        self.lock_token=token

    def release(self):
        if not self.lock_token: return
        try:
            self.run('/system/script/environment/remove [find where name="mikrowarpAdminLock"]; /system/script/environment/remove [find where name="mikrowarpAdminUntil"]')
        finally:self.lock_token=None

    def rows(self, menu, condition=''):
        raw=self.run(':put [:serialize to=json ['+menu+' print as-value'+
                     (' where '+condition if condition else '')+']]')
        if not raw:return []
        value=json.loads(raw)
        if value is None or value=={}:return []
        return [value] if isinstance(value,dict) else value

    def copy(self, source, destination, download=False):
        if self.lock_token:self.run(':put "transfer"')
        remote=self.user+'@'+self.host+':'+(source if download else destination)
        args=[remote, destination] if download else [source, remote]
        subprocess.run(['scp', '-O', '-q', '-P', str(self.profile.get('port', 22))]+self.options+args,
                       check=True, timeout=600)
        if self.lock_token:self.run(':put "transfer_complete"')

    def shell(self, name, command, timeout=45, check=True):
        script=command+'\nrc=$?\nprintf "\\n__MW_EXIT=%s\\n" "$rc"'
        value=self.run('/container/shell [find where name='+quote(name)+'] cmd='+quote(script), timeout, shell_marker=True)
        if '__MW_EXIT=' not in value: raise RuntimeError('Container shell returned no exit marker')
        value,code=value.rsplit('__MW_EXIT=',1); code=int(code.strip().splitlines()[0])
        if check and code: raise RuntimeError('Container command failed: '+value.strip())
        return code,value.strip()
