"""Read helpers for the original runtime fixture, retained by continuity tests.

The retired computer-side installer is preserved in Git history. These helpers
inspect its existing loopback fixture; they cannot install, update or roll back.
"""
import hashlib
import json
import re
import time

from .transport import Router, quote


def wait_for(predicate, seconds=360):
    start = time.monotonic()
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() - start > seconds:
            raise TimeoutError('Lab condition did not recover')
        time.sleep(3)


class Gateway:
    def __init__(self, profile):
        self.r = Router(profile)
        self.base = profile['directory'].strip('/')
        if not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*', self.base):
            raise ValueError('Invalid fixture directory')

    def rows(self, menu, condition=''):
        return self.r.rows(menu, condition)

    def read(self, path):
        if not self.rows('/file', 'name=' + quote(path)):
            return None
        return self.r.run(':put [/file/get [find where name=' + quote(path) + '] contents]')

    def container(self, name='mikrowarp'):
        rows = self.rows('/container', 'name=' + quote(name))
        if len(rows) > 1:
            raise RuntimeError('Container name is ambiguous')
        if rows and not rows[0].get('downloading/extracting'):
            rows[0]['image-id'] = self.r.run(':put [/container/get ' + quote(rows[0]['.id']) + ' image-id]')
        return rows[0] if rows else None

    def ready(self):
        try:
            return self.r.shell('mikrowarp', '/usr/local/sbin/mikrowarp', check=False)[0] == 0
        except (RuntimeError, TimeoutError):
            return False

    def record(self, name):
        value = self.read(self.base + '/' + name + '.json')
        return json.loads(value) if value else None

    def pending(self):
        valid = []
        for slot in (0, 1):
            text = self.read(self.base + '/operation.' + str(slot) + '.json')
            if not text:
                continue
            try:
                row = json.loads(text)
                packed = json.dumps(row['payload'], sort_keys=True, separators=(',', ':'))
                if hashlib.sha256(packed.encode()).hexdigest() == row['sha256']:
                    valid.append(row['payload'])
            except (ValueError, KeyError, TypeError):
                pass
        job = max(valid, key=lambda row: row['sequence']) if valid else None
        return job if job and job['phase'] not in ('complete', 'aborted') else None
