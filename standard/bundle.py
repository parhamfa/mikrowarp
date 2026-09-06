#!/usr/bin/env python3
"""Export and independently verify an immutable, amd64 Standard bundle."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

BASE_ID='sha256:cd6cb165c8e780cfa700cf300e2a4aa64158b7992c888326830e75cf5b4236b2'
BASE_TAG='local/warp-masque-gateway:2026.7.1377.0-r11-pilot'
TAG='local/mikrowarp:2026.7.1377.0-r14-standard'
ROOT=Path(__file__).resolve().parents[1]

def verify(path,image_id,tag):
    small={};hashes={}
    with gzip.open(path,'rb') as stream:
        with tarfile.open(fileobj=stream,mode='r|') as archive:
            for member in archive:
                if not member.isfile(): continue
                h=hashlib.sha256();payload=bytearray()
                file=archive.extractfile(member)
                while chunk:=file.read(1024*1024):
                    h.update(chunk)
                    if member.size<262144: payload.extend(chunk)
                hashes[member.name]=h.hexdigest()
                if re.fullmatch(r'blobs/sha256/[0-9a-f]{64}',member.name):
                    if h.hexdigest()!=member.name.rsplit('/',1)[1]: raise ValueError('Archive blob checksum mismatch')
                if payload: small[member.name]=bytes(payload)
        while stream.read(1024*1024): pass
    manifests=json.loads(small['manifest.json'])
    if len(manifests)!=1 or tag not in manifests[0]['RepoTags']: raise ValueError('Unexpected archive manifest')
    manifest=manifests[0]
    if 'sha256:'+hashes[manifest['Config']]!=image_id: raise ValueError('Image configuration checksum mismatch')
    config=json.loads(small[manifest['Config']])
    if config['architecture']!='amd64': raise ValueError('Wrong image architecture')
    # Docker save uses uncompressed layer tar streams; validate every diff ID too.
    if ['sha256:'+hashes[name] for name in manifest['Layers']]!=config['rootfs']['diff_ids']:
        raise ValueError('Image layer checksum mismatch')
    return {'gzip_crc':'pass','archive_blob_hashes':'pass','layer_diff_ids':'pass','image_id':image_id}

def export(tag,output):
    output.mkdir(parents=True,exist_ok=True)
    obj=json.loads(subprocess.check_output(['docker','image','inspect',tag]))[0]
    path=output/'image.tar.gz';partial=output/'image.tar.gz.partial'
    if path.exists(): raise FileExistsError('Use a new output directory to preserve earlier evidence')
    process=subprocess.Popen(['docker','save',tag],stdout=subprocess.PIPE)
    with partial.open('wb') as target, gzip.GzipFile(filename='',fileobj=target,mode='wb',compresslevel=6,mtime=0) as z:
        shutil.copyfileobj(process.stdout,z)
    if process.wait(): raise RuntimeError('Docker export failed')
    checks=verify(partial,obj['Id'],tag);partial.replace(path)
    with path.open('rb') as f: digest=hashlib.file_digest(f,'sha256').hexdigest()
    info={'tag':tag,'image_id':obj['Id'],'architecture':'amd64','edition':'standard',
          'logical_bytes':obj['Size'],'archive_bytes':path.stat().st_size,'sha256':digest,'verified':checks}
    (output/'image.json').write_text(json.dumps(info,indent=2)+'\n')
    (output/'image.tar.gz.sha256').write_text(digest+'  image.tar.gz\n')
    print(json.dumps(info,indent=2),flush=True)
    return info

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--tag',default=TAG);p.add_argument('--build',action='store_true');a=p.parse_args()
    if a.build:
        base=json.loads(subprocess.check_output(['docker','image','inspect',BASE_TAG]))[0]
        if base['Id']!=BASE_ID: raise ValueError('Preserved r11 base image ID differs')
        subprocess.run(['docker','build','--platform','linux/amd64','-f','standard/Dockerfile','-t',a.tag,'.'],cwd=ROOT,check=True)
    export(a.tag,a.output)
