"""Prepare a new release directory without changing a published image or installer."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from .image import verify
from .installer import render


def prepare(version, bundle, output):
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', version):
        raise ValueError('Use a release version such as v1.0.1')
    bundle = Path(bundle)
    output = Path(output)
    if output.exists():
        raise FileExistsError('Use a new release output directory')
    info = json.loads((bundle / 'image.json').read_text())
    archive = bundle / 'image.tar.gz'
    with archive.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if archive.stat().st_size != info['archive_bytes'] or digest != info['sha256']:
        raise ValueError('Bundle archive does not match its recorded size and SHA-256')
    verify(archive, info['image_id'], info['tag'])
    filename = 'mikrowarp-linux-amd64.tar.gz'
    metadata = {key: info[key] for key in ('sha256', 'archive_bytes', 'logical_bytes')}
    metadata.update(image_id=info['image_id'].removeprefix('sha256:'), revision=version,
                    url=f'https://github.com/parhamfa/mikrowarp/releases/download/{version}/{filename}')
    installer = render(metadata)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        stage = Path(temporary) / 'release'
        stage.mkdir()
        shutil.copyfile(archive, stage / filename)
        (stage / (filename + '.sha256')).write_text(digest + '  ' + filename + '\n')
        (stage / 'mikrowarp.rsc').write_text(installer)
        installer_digest = hashlib.sha256(installer.encode()).hexdigest()
        (stage / 'mikrowarp.rsc.sha256').write_text(installer_digest + '  mikrowarp.rsc\n')
        (stage / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
        stage.rename(output)
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.version, args.bundle, args.output))
