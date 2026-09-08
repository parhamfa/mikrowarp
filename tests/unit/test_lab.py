import unittest
from unittest.mock import patch

from tests.lab.gateway import Gateway
from tests.lab.transport import Router


class LabBoundaryTests(unittest.TestCase):
    def profile(self, **overrides):
        return dict({'host': '127.0.0.1', 'port': 23223, 'identity': 'mikrowarp-native-lab',
                     'key': '/unused/test-key', 'known_hosts': '/unused/test-known-hosts'}, **overrides)

    def test_transport_rejects_other_hosts_ports_and_identities_before_ssh(self):
        for overrides in ({'host': '192.0.2.1'}, {'host': 'localhost'}, {'port': 22},
                          {'identity': 'production'}, {'port': 23223, 'identity': 'mikrowarp-standard-lab'}):
            with self.subTest(overrides=overrides), patch('tests.lab.transport.subprocess.run') as ssh:
                with self.assertRaises(ValueError):
                    Router(self.profile(**overrides))
                ssh.assert_not_called()

    def test_old_runtime_helper_has_no_installation_entry_points(self):
        gateway = Gateway(self.profile(directory='pcie1/mikrowarp'))
        for method in ('install', 'begin_update', 'begin_rollback', 'resume', 'abort', 'network'):
            self.assertFalse(hasattr(gateway, method))

    def test_moved_lab_and_renderer_import_without_launching_anything(self):
        with patch('subprocess.run') as run, patch('subprocess.Popen') as start:
            from tests.lab import acceptance, control, vm
            from tools import installer
            self.assertEqual(control.ROOT, installer.ROOT)
            self.assertEqual(vm.ROOT, installer.ROOT)
            self.assertTrue(callable(acceptance.Acceptance))
            run.assert_not_called()
            start.assert_not_called()
