import hashlib
import json
from pathlib import Path
import shutil
import sys

root=Path(sys.argv[1]);source=Path('/source')
legacy=root/'var/lib/cloudflare-warp'
assert not any(legacy.iterdir()), 'A release image must not contain registration material'
legacy.rmdir();legacy.symlink_to('/var/lib/mikrowarp/state')
for d in ['usr/local/lib/mikrowarp','usr/local/libexec','var/lib/mikrowarp','run/mikrowarp','etc/netns']:
    (root/d).mkdir(parents=True,exist_ok=True)
for name in ['common.sh','probe.sh','storage.sh','status.sh','gateway.sh','maintenance.sh']:
    target=root/'usr/local/lib/mikrowarp'/name
    shutil.copyfile(source/name,target);target.chmod(0o755)
(root/'usr/local/sbin/mikrowarp').symlink_to('/usr/local/lib/mikrowarp/status.sh')
record={'edition':'standard','revision':'2026.7.1377.0-r14-standard',
        'base_image_id':'sha256:cd6cb165c8e780cfa700cf300e2a4aa64158b7992c888326830e75cf5b4236b2',
        'ipv4_only':True,'router_traffic_policy':'administrator-owned',
        'health':'expiring ICMP readiness backed by internal forwarded probes',
        'sources':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file()}}
(root/'usr/share/mikrowarp/standard.json').write_text(json.dumps(record,indent=2)+'\n')
