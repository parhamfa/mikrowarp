"""Offline source, generated-installer and documentation checks."""
import ast
from pathlib import Path
import platform
import re
import shutil
import subprocess
from urllib.parse import unquote

from .installer import DEFAULT, ROOT, render


def check():
    sources = [path for folder in ('src', 'tools', 'tests') for path in (ROOT / folder).rglob('*')
               if path.is_file() and '__pycache__' not in path.parts]
    for path in sources:
        if path.suffix == '.py':
            ast.parse(path.read_text(), filename=str(path))
        elif path.suffix == '.sh':
            subprocess.run(['bash', '-n', str(path)], check=True)
    shellcheck = shutil.which('shellcheck')
    if shellcheck is None:
        raise RuntimeError('Install shellcheck to run make check')
    scripts = [str(path) for path in sources if path.suffix == '.sh']
    subprocess.run([shellcheck, '--severity=error', *scripts], check=True)
    if platform.system() == 'Linux':
        subprocess.run(['cc', '-O2', '-Wall', '-Wextra', '-Werror', '-fsyntax-only',
                        str(ROOT / 'src/container/io.c')], check=True)
    assert (ROOT / 'mikrowarp.rsc').read_text() == render(DEFAULT), 'Generated installer is stale: run make installer'
    documents = list(ROOT.glob('*.md')) + list((ROOT / 'docs').rglob('*.md')) + list((ROOT / 'tests').rglob('*.md'))
    for document in documents:
        for match in re.finditer(r'!?\[[^\]\n]*\]\(([^)\n]+)\)', document.read_text()):
            target = match[1].split('#', 1)[0]
            if not target or re.match(r'[a-zA-Z][a-zA-Z0-9+.-]*:', target):
                continue
            destination = (document.parent / unquote(target)).resolve()
            assert destination.is_relative_to(ROOT), f'Link leaves repository: {document}: {target}'
            assert destination.exists(), f'Broken link: {document.relative_to(ROOT)}: {target}'
    print('Python, shell, generated installer and documentation checks passed.')


if __name__ == '__main__':
    check()
