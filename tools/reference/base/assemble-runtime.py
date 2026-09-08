#!/usr/bin/env python3
"""Assemble a small Ubuntu/glibc root, preserving vendor and library bytes.

This runs only in the build stage. ELF dependencies are discovered using the
Ubuntu loader; runtime-loaded modules and data are explicitly retained below.
No stripping, binary patching, compatibility shim, or package manager ships.
"""
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess

ROOT = Path('/rootfs')
ROOT.mkdir()
copied = set()
pending = []
scanned = set()


def copy(source):
    source = Path(source)
    # Resolve parent aliases (Ubuntu's merged /usr) without dereferencing the
    # leaf symlink. Never follow an absolute symlink in the destination root.
    source = source.parent.resolve() / source.name
    if str(source) in copied:
        return
    copied.add(str(source))
    dest = ROOT / str(source).lstrip('/')
    dest.parent.mkdir(parents=True, exist_ok=True)
    info = source.lstat()
    if source.is_symlink():
        target = Path(os.readlink(source))
        dest.symlink_to(str(target))
        # Preserve intermediate links too (for example awk -> alternatives -> mawk).
        copy(target if target.is_absolute() else source.parent / target)
    elif source.is_dir():
        dest.mkdir(exist_ok=True)
        for child in sorted(source.iterdir()):
            copy(child)
        os.chmod(dest, stat.S_IMODE(info.st_mode))
    elif source.is_file():
        shutil.copy2(source, dest)
        with source.open('rb') as file:
            if file.read(4) == b'\x7fELF':
                pending.append(str(source))
    else:
        raise RuntimeError('Unexpected special build file: ' + str(source))
    os.chown(dest, info.st_uid, info.st_gid, follow_symlinks=False)
    if not source.is_symlink():
        os.chmod(dest, stat.S_IMODE(info.st_mode))


for alias in ['bin', 'sbin', 'lib', 'lib64']:
    source = Path('/') / alias
    if source.is_symlink():
        (ROOT / alias).symlink_to(os.readlink(source))
        (ROOT / str(source.resolve()).lstrip('/')).mkdir(parents=True, exist_ok=True)

# Preserve the GNU/Bash semantics used by the unchanged gateway and lab checks.
# Small operational tools also support inspecting a running RouterOS container.
commands = '''bash sh env cat date mv mkdir mknod chmod chown rm sleep stat
truncate timeout mktemp touch grep sed awk uname getent sha256sum printenv sort
wc head tail cut tr readlink ls du id dd cp ln df find xargs pgrep pkill ps free
sysctl ip ss nft curl dig host certutil pk12util modutil dbus-daemon dbus-uuidgen
openssl logger tar gzip'''.split()
for command in commands:
    path = shutil.which(command)
    if not path:
        raise RuntimeError('Required command absent: ' + command)
    copy(path)
for name in ['warp-svc', 'warp-cli', 'warp-diag', 'warp-dex']:
    copy('/usr/bin/' + name)
for name in ['warp-gateway', 'warp-gateway-health', 'warp-gateway-probe']:
    copy('/usr/local/sbin/' + name)

required_data = [
    '/etc/passwd', '/etc/group', '/etc/shadow', '/etc/gshadow',
    '/etc/nsswitch.conf', '/etc/host.conf', '/etc/gai.conf',
    '/etc/ld.so.conf', '/etc/ld.so.conf.d',
    '/etc/os-release', '/etc/debian_version',
    '/etc/ssl', '/usr/share/ca-certificates', '/etc/dbus-1',
    '/usr/share/dbus-1', '/usr/lib/dbus-1.0/dbus-daemon-launch-helper',
    '/usr/share/doc/cloudflare-warp', '/usr/share/mikrowarp',
    '/usr/share/common-licenses',
]
for path in required_data:
    copy(path)
for path in ['/etc/lsb-release', '/etc/networks', '/etc/services', '/etc/protocols',
             '/etc/localtime', '/etc/timezone',
             '/etc/machine-id', '/var/lib/dbus/machine-id', '/etc/iproute2',
             '/usr/share/iproute2', '/usr/lib/locale/C.utf8']:
    if Path(path).exists():
        copy(path)

# ldd alone misses dlopen modules: NSS crypto/name lookup, TPM transports,
# OpenSSL providers, glibc character conversion, and Kerberos plugins.
module_patterns = [
    '/usr/lib/*-linux-gnu/libnss_*.so*',
    '/usr/lib/*-linux-gnu/libfreebl*',
    '/usr/lib/*-linux-gnu/nss',
    '/usr/lib/*-linux-gnu/libtss2-tcti-*.so*',
    '/usr/lib/*-linux-gnu/engines-3', '/usr/lib/*-linux-gnu/ossl-modules',
    '/usr/lib/*-linux-gnu/gconv', '/usr/lib/*-linux-gnu/krb5/plugins',
]
for pattern in module_patterns:
    for path in sorted(glob.glob(pattern)):
        copy(path)

while pending:
    path = pending.pop()
    if path in scanned:
        continue
    scanned.add(path)
    result = subprocess.run(['ldd', path], text=True, capture_output=True)
    output = result.stdout + result.stderr
    if 'not found' in output:
        raise RuntimeError('Unresolved dependency: ' + path + '\n' + output)
    if result.returncode and not any(x in output for x in [
            'not a dynamic executable', 'statically linked']):
        raise RuntimeError('ldd failed: ' + path + '\n' + output)
    for dependency in re.findall(r'(?:=>\s+|^\s*)(/[^\s()]+)', output, re.M):
        copy(dependency)

# Retain attribution for every Debian package contributing copied files, plus
# their exact versions. The installed-package database itself is build-only.
owners = {}
for listing in Path('/var/lib/dpkg/info').glob('*.list'):
    package = listing.name[:-5]
    for path in listing.read_text().splitlines():
        if path.startswith('/'):
            normalized = str(Path(path).parent.resolve() / Path(path).name)
            owners.setdefault(normalized, set()).add(package)
packages = set()
for path in copied:
    if Path(path).is_file() or Path(path).is_symlink():
        packages.update(owners.get(path, set()))
package_records = []
for package in sorted(packages):
    fields = subprocess.check_output(['dpkg-query', '-W',
        '-f=${binary:Package}\t${Version}\t${Architecture}', package], text=True).split('\t')
    copyright_path = Path('/usr/share/doc') / package.split(':')[0] / 'copyright'
    if not copyright_path.exists():
        raise RuntimeError('Missing package copyright: ' + package)
    copy(copyright_path)
    package_records.append(dict(zip(['package', 'version', 'architecture'], fields)))

for directory in ['dev', 'proc', 'sys', 'run', 'run/dbus', 'run/mikrowarp',
                  'tmp', 'var/tmp', 'var/log', 'var/lib/cloudflare-warp',
                  'var/lib/dbus', 'root', 'etc']:
    (ROOT / directory).mkdir(parents=True, exist_ok=True)
for directory in ['tmp', 'var/tmp']:
    (ROOT / directory).chmod(0o1777)
(ROOT / 'root').chmod(0o700)
for name in ['hosts', 'resolv.conf', 'hostname']:
    (ROOT / 'etc' / name).touch()  # Supplied by the container runtime.
(ROOT / 'var/run').symlink_to('/run')
(ROOT / 'var/lock').symlink_to('/run/lock')

# Build a loader cache containing only libraries actually copied into this root.
subprocess.run(['ldconfig', '-r', str(ROOT)], check=True)
loader = next(ROOT.glob('usr/lib/*-linux-gnu/ld-linux-*.so*'))
loader_path = '/' + str(loader.relative_to(ROOT))
for command in commands + ['warp-svc', 'warp-cli', 'warp-diag', 'warp-dex']:
    subprocess.run(['chroot', str(ROOT), loader_path, '--list', shutil.which(command)],
                   check=True, stdout=subprocess.DEVNULL)
files = []
for path in sorted(ROOT.rglob('*')):
    relative = '/' + str(path.relative_to(ROOT))
    if path.is_symlink():
        files.append({'path': relative, 'symlink': os.readlink(path)})
    elif path.is_file():
        files.append({'path': relative, 'bytes': path.stat().st_size,
                      'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
manifest = {'method': 'Ubuntu file allowlist, ELF closure, explicit runtime modules',
            'commands': commands, 'module_patterns': module_patterns,
            'packages': package_records, 'files': files,
            'file_bytes_before_manifest': sum(x.get('bytes', 0) for x in files)}
(ROOT / 'usr/share/mikrowarp/runtime-manifest.json').write_text(
    json.dumps(manifest, indent=2) + '\n')
print(json.dumps({'packages_retained': len(package_records), 'files': len(files),
                  'file_bytes_before_manifest': manifest['file_bytes_before_manifest']}))
