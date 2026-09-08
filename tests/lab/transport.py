"""SSH transport restricted to the named, loopback-only QEMU fixtures."""
import json
import re
import subprocess

def quote(value):
    return '"' + str(value).replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$').replace('\n', '\\n') + '"'

class Router:
    def __init__(self, profile):
        self.profile = profile
        self.host = profile['host']
        allowed = {(23222, 'mikrowarp-standard-lab'), (23222, 'mikrowarp-native-lab'),
                   (23223, 'mikrowarp-native-lab')}
        if self.host != '127.0.0.1' or (profile.get('port'), profile.get('identity')) not in allowed:
            raise ValueError('Test transport accepts only the dedicated loopback QEMU fixtures')
        self.user = profile.get('user', 'admin')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', self.user): raise ValueError('Invalid SSH user')
        self.options = ['-F', '/dev/null', '-i', profile['key'], '-o', 'IdentitiesOnly=yes',
            '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=8',
            '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
            '-o', 'UserKnownHostsFile='+profile['known_hosts'], '-o', 'LogLevel=ERROR']

    def run(self, command, timeout=60, shell_marker=False):
        guard = ':if ([/system/identity get name] != '+quote(self.profile['identity'])+') do={ :error "Router identity mismatch" }; '
        text = ':onerror e in={ '+guard+command+'; :put "__MW_OK__" } do={ :put ("__MW_ERROR__".$e) }'
        result = subprocess.run(['ssh', '-p', str(self.profile.get('port', 22))]+self.options+
            [self.user+'@'+self.host, text], capture_output=True, text=True, timeout=timeout)
        completed='__MW_OK__' in result.stdout or (shell_marker and '__MW_EXIT=' in result.stdout)
        if result.returncode or not completed or '__MW_ERROR__' in result.stdout:
            raise RuntimeError((result.stdout+result.stderr).strip())
        return result.stdout.replace('__MW_OK__', '').strip()

    def rows(self, menu, condition=''):
        raw=self.run(':put [:serialize to=json ['+menu+' print as-value'+
                     (' where '+condition if condition else '')+']]')
        if not raw:return []
        value=json.loads(raw)
        if value is None or value=={}:return []
        return [value] if isinstance(value,dict) else value

    def copy(self, source, destination, download=False):
        remote=self.user+'@'+self.host+':'+(source if download else destination)
        args=[remote, destination] if download else [source, remote]
        subprocess.run(['scp', '-O', '-q', '-P', str(self.profile.get('port', 22))]+self.options+args,
                       check=True, timeout=600)

    def shell(self, name, command, timeout=45, check=True):
        script=command+'\nrc=$?\nprintf "\\n__MW_EXIT=%s\\n" "$rc"'
        value=self.run('/container/shell [find where name='+quote(name)+'] cmd='+quote(script), timeout, shell_marker=True)
        if '__MW_EXIT=' not in value: raise RuntimeError('Container shell returned no exit marker')
        value,code=value.rsplit('__MW_EXIT=',1); code=int(code.strip().splitlines()[0])
        if check and code: raise RuntimeError('Container command failed: '+value.strip())
        return code,value.strip()
