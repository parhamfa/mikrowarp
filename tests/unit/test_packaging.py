import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import image
from tools.image import download_verified, verify
from tools.installer import DEFAULT, ROOT, render
from tools.release import prepare


def bundle_fixture(directory):
    """A tiny Docker-save archive with real configuration and layer digests."""
    directory.mkdir()
    layer = b'fixture layer bytes'
    layer_hash = hashlib.sha256(layer).hexdigest()
    config = json.dumps({'architecture': 'amd64', 'rootfs': {'diff_ids': ['sha256:' + layer_hash]}}).encode()
    config_hash = hashlib.sha256(config).hexdigest()
    tag = 'fixture/image:test'
    config_name = 'blobs/sha256/' + config_hash
    layer_name = 'blobs/sha256/' + layer_hash
    manifest = json.dumps([{'Config': config_name, 'RepoTags': [tag], 'Layers': [layer_name]}]).encode()
    archive = directory / 'image.tar.gz'
    with tarfile.open(archive, 'w:gz') as output:
        for name, body in [('manifest.json', manifest), (config_name, config), (layer_name, layer)]:
            member = tarfile.TarInfo(name)
            member.size = len(body)
            output.addfile(member, io.BytesIO(body))
    info = {'tag': tag, 'image_id': 'sha256:' + config_hash, 'logical_bytes': len(layer),
            'archive_bytes': archive.stat().st_size, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
    (directory / 'image.json').write_text(json.dumps(info))
    return info


class InstallerTests(unittest.TestCase):
    def test_committed_installer_matches_sources(self):
        self.assertEqual(render(DEFAULT), (ROOT / 'mikrowarp.rsc').read_text())

    def test_metadata_cannot_inject_routeros_code(self):
        for key, value in [('url', 'http://example.invalid/image'), ('url', 'https://example.invalid/";bad'),
                           ('url', 'https://example.invalid/$bad'), ('revision', 'v1\n:bad'),
                           ('image_id', 'x' * 64), ('archive_bytes', True), ('logical_bytes', 2**31)]:
            with self.subTest(key=key, value=value), self.assertRaises(AssertionError):
                render(dict(DEFAULT, **{key: value}))


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / 'bundle'
        self.info = bundle_fixture(self.bundle)

    def test_archive_identity_and_tag_are_checked(self):
        verify(self.bundle / 'image.tar.gz', self.info['image_id'], self.info['tag'])
        for image, tag in [('sha256:' + '0' * 64, self.info['tag']), (self.info['image_id'], 'wrong:tag')]:
            with self.subTest(image=image, tag=tag), self.assertRaises(ValueError):
                verify(self.bundle / 'image.tar.gz', image, tag)

    def test_truncated_archive_is_rejected(self):
        archive = self.bundle / 'image.tar.gz'
        archive.write_bytes(archive.read_bytes()[:-7])
        with self.assertRaises((EOFError, OSError, tarfile.TarError)):
            verify(archive, self.info['image_id'], self.info['tag'])

    def test_release_preserves_image_and_pins_its_own_version(self):
        output = prepare('v1.2.3', self.bundle, self.root / 'release')
        self.assertEqual((output / 'mikrowarp-linux-amd64.tar.gz').read_bytes(), (self.bundle / 'image.tar.gz').read_bytes())
        metadata = json.loads((output / 'metadata.json').read_text())
        self.assertIn('/releases/download/v1.2.3/', metadata['url'])
        self.assertEqual(metadata['image_id'], self.info['image_id'].removeprefix('sha256:'))
        self.assertEqual((output / 'mikrowarp.rsc').read_text(), render(metadata))
        for filename in ('mikrowarp.rsc', 'mikrowarp-linux-amd64.tar.gz'):
            expected = hashlib.sha256((output / filename).read_bytes()).hexdigest()
            self.assertEqual((output / (filename + '.sha256')).read_text(), expected + '  ' + filename + '\n')

    def test_release_rejects_corruption_without_leaving_output(self):
        archive = self.bundle / 'image.tar.gz'
        archive.write_bytes(archive.read_bytes() + b'bad')
        with self.assertRaises(ValueError):
            prepare('v1.2.3', self.bundle, self.root / 'release')
        self.assertFalse((self.root / 'release').exists())

    def test_release_cannot_overwrite_an_existing_directory(self):
        output = self.root / 'release'
        output.mkdir()
        (output / 'keep').write_text('existing release')
        with self.assertRaises(FileExistsError):
            prepare('v1.2.3', self.bundle, output)
        self.assertEqual((output / 'keep').read_text(), 'existing release')

    def test_missing_reference_is_verified_before_docker_load(self):
        from subprocess import CompletedProcess
        payload = (self.bundle / 'image.tar.gz').read_bytes()
        response = io.BytesIO(payload)
        response.url = 'https://example.invalid/reference'
        with patch.object(image, 'ROOT', self.root), \
                patch.object(image, 'BASE_TAG', self.info['tag']), \
                patch.object(image, 'BASE_ID', self.info['image_id']), \
                patch.object(image, 'BASE_SHA256', self.info['sha256']), \
                patch.object(image, 'BASE_BYTES', len(payload)), \
                patch('tools.image.urllib.request.urlopen', return_value=response), \
                patch('tools.image.subprocess.run', side_effect=[CompletedProcess([], 1), CompletedProcess([], 0), CompletedProcess([], 0)]) as docker, \
                patch('tools.image.subprocess.check_output', return_value=json.dumps([{'Id': self.info['image_id']}]).encode()):
            image.ensure_reference()
        load = docker.call_args_list[-1].args[0]
        self.assertEqual(load[:3], ['docker', 'load', '-i'])
        self.assertEqual(Path(load[3]).read_bytes(), payload)

    def test_wrong_installed_reference_is_not_replaced(self):
        from subprocess import CompletedProcess
        with patch('tools.image.subprocess.run', return_value=CompletedProcess([], 0, stdout='[{"Id":"wrong"}]')), \
                patch('tools.image.urllib.request.urlopen') as download:
            with self.assertRaises(ValueError):
                image.ensure_reference()
            download.assert_not_called()


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.destination = Path(self.temporary.name) / 'reference.tar.gz'
        self.body = b'known build input'
        self.digest = hashlib.sha256(self.body).hexdigest()

    def fetch(self):
        return download_verified('https://example.invalid/reference', self.destination, self.digest, len(self.body))

    def response(self, body):
        value = io.BytesIO(body)
        value.url = 'https://example.invalid/reference'
        return value

    def test_verified_download_is_reused_without_network(self):
        with patch('tools.image.urllib.request.urlopen', return_value=self.response(self.body)) as request:
            self.fetch()
            self.fetch()
        self.assertEqual(request.call_count, 1)
        self.assertEqual(self.destination.read_bytes(), self.body)

    def test_incomplete_or_wrong_download_does_not_poison_cache(self):
        for body in (self.body[:-1], self.body + b'x', b'x' * len(self.body)):
            with self.subTest(body=body), patch('tools.image.urllib.request.urlopen', return_value=self.response(body)):
                with self.assertRaises(ValueError):
                    self.fetch()
            self.assertEqual(list(self.destination.parent.iterdir()), [])

    def test_disconnected_download_cleans_up_partial_file(self):
        response = self.response(self.body)
        with patch.object(response, 'read', side_effect=[self.body[:3], ConnectionResetError()]), \
                patch('tools.image.urllib.request.urlopen', return_value=response):
            with self.assertRaises(ConnectionResetError):
                self.fetch()
        self.assertEqual(list(self.destination.parent.iterdir()), [])
