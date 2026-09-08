#!/usr/bin/env python3
"""Render the single downloadable RouterOS script; users do not run this tool."""
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = {
    'image_id': 'f54570f4b9ede63f337640053a4daccf5da70d0cdfe04f2330ecebaf26a93f39',
    'sha256': 'abb7dd5220e38d146185455b7427c019337d0e83e983bf0e37929febd3193da1',
    'archive_bytes': 93635286, 'logical_bytes': 264691612,
    'url': 'https://github.com/parhamfa/mikrowarp/releases/download/v1.0.0/mikrowarp-linux-amd64.tar.gz',
    'revision': 'v1.0.0',
}


def render(metadata):
    for key in ('image_id', 'sha256'):
        assert re.fullmatch('[0-9a-f]{64}', metadata[key])
    assert metadata['url'].startswith('https://') and not any(c in metadata['url'] for c in '\\"$\n')
    assert re.fullmatch('[a-zA-Z0-9._-]+', metadata['revision'])
    for key in ('archive_bytes', 'logical_bytes'):
        assert type(metadata[key]) is int and 0 < metadata[key] < 2**31
    value = ';'.join('"' + key + '"=' + (str(v) if type(v) is int else '"' + v + '"') for key, v in ((key, metadata[key]) for key in DEFAULT))
    source = ROOT / 'src/routeros'
    worker = (source / 'worker.rsc').read_text().replace('@@RELEASE@@', '{' + value + '}')
    worker = worker.replace('# @@OPERATIONS@@', (source / 'operations.rsc').read_text() + '\n' + (source / 'main.rsc').read_text())
    worker = worker.replace('# @@MAIN@@', '$mikrowarpNativeMain action=$action')
    result = (source / 'bootstrap.rsc').read_text().replace('@@WORKER@@', worker)
    assert '@@' not in result
    # RouterOS scripts and file contents have bounded sizes.
    assert len(result.encode()) < 60000, 'Installer must remain below the RouterOS file-content limit'
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'mikrowarp.rsc')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    content = render(json.loads(args.metadata.read_text()) if args.metadata else DEFAULT)
    if args.check:
        assert args.output.read_text() == content, 'Generated installer is stale'
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content)
    print(f'{args.output}: {len(content.encode())} bytes')
