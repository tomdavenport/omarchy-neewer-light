"""Install into disposable folders; never call systemd, pip or real Bluetooth."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / (name + '.py'))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.app = self.home / '.local/share/neewer-omarchy'
        self.installer = module('install_backend')
        self.active, self.enabled = False, False
        self.commands = []
        self.fail_enable = False
        self.fail_download = False

    def process(self, args, **kwargs):
        self.commands.append(args)
        if '-m' in args and 'venv' in args:
            interpreter = Path(args[-1]) / 'bin/python'
            interpreter.parent.mkdir(parents=True)
            interpreter.write_text('candidate runtime')
        if 'pip' in args and self.fail_download:
            raise subprocess.CalledProcessError(1, args)
        if args[:2] == ['systemctl', '--user']:
            if args[2] == 'is-active':
                return subprocess.CompletedProcess(args, 0 if self.active else 3)
            if args[2] == 'is-enabled':
                return subprocess.CompletedProcess(args, 0 if self.enabled else 1)
            if args[2] == 'enable' and self.fail_enable:
                raise subprocess.CalledProcessError(1, args)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps({'ok': True}))

    def install(self):
        with patch.object(self.installer.subprocess, 'run', side_effect=self.process):
            self.installer.install(self.home)

    def existing(self):
        self.app.mkdir(parents=True)
        old = self.app / 'venv/bin/python'
        old.parent.mkdir(parents=True)
        old.write_text('previous runtime')
        (self.app / 'controller.py').write_text('previous controller')
        (self.app / 'installed-version').write_text('2.3.0\n')
        cfg = self.home / '.config/neewer-omarchy/config.json'
        cfg.parent.mkdir(parents=True)
        cfg.write_text('{"brightness":37,"role":"alternate"}')
        self.active, self.enabled = True, True
        return cfg

    def test_fresh_install_waits_for_status_and_preserves_preferences(self):
        cfg = self.home / '.config/neewer-omarchy/config.json'
        cfg.parent.mkdir(parents=True)
        cfg.write_text('{"brightness":37}')
        self.install()
        self.assertEqual(cfg.read_text(), '{"brightness":37}')
        self.assertTrue((self.app / 'venv').is_symlink())
        self.assertEqual((self.app / 'installed-version').read_text().strip(), '2.4.0')
        self.assertEqual(self.app.stat().st_mode & 0o777, 0o700)
        self.assertTrue(any(c[-1] == 'status' for c in self.commands))
        self.assertTrue((self.home / '.local/bin/neewer-light').exists())

    def test_upgrade_builds_dependencies_before_stopping_old_runtime(self):
        cfg = self.existing()
        self.install()
        pip = next(i for i,c in enumerate(self.commands) if 'pip' in c)
        stop = next(i for i,c in enumerate(self.commands) if c[:3] == ['systemctl','--user','stop'])
        self.assertLess(pip, stop)
        self.assertNotIn(str(self.app / 'venv/bin/python'), self.commands[pip])
        self.assertEqual(cfg.read_text(), '{"brightness":37,"role":"alternate"}')
        backups = list((self.app / 'backups').glob('*/previous-venv/bin/python'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), 'previous runtime')

    def test_failed_upgrade_restores_runtime_source_and_marker(self):
        cfg = self.existing()
        self.fail_enable = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.install()
        self.assertEqual((self.app / 'venv/bin/python').read_text(), 'previous runtime')
        self.assertEqual((self.app / 'controller.py').read_text(), 'previous controller')
        self.assertEqual((self.app / 'installed-version').read_text().strip(), '2.3.0')
        self.assertEqual(cfg.read_text(), '{"brightness":37,"role":"alternate"}')
        self.assertEqual(list((self.app / 'environments').iterdir()), [])
        self.assertIn(['systemctl','--user','start','neewer-light.service'], self.commands)

    def test_failed_download_never_stops_or_mutates_existing_runtime(self):
        self.existing()
        self.fail_download = True
        with self.assertRaises(subprocess.CalledProcessError):
            self.install()
        self.assertFalse(any(c[:3] == ['systemctl','--user','stop'] for c in self.commands))
        self.assertEqual((self.app / 'controller.py').read_text(), 'previous controller')
        self.assertEqual(list((self.app / 'environments').iterdir()), [])

    def test_initial_status_never_installs_or_starts_services(self):
        control = module('control')
        with patch.object(control, 'APP', self.app), patch.object(control.sys, 'argv', ['control.py','status']), \
                patch.object(control.subprocess, 'run') as run:
            snapshot = control.main()
        self.assertFalse(snapshot['backend_ready'])
        self.assertFalse(snapshot['configured'])
        run.assert_not_called()

    def test_version_mismatch_requires_explicit_setup(self):
        self.existing()
        control = module('control')
        with patch.object(control, 'APP', self.app):
            self.assertFalse(control.ready())


if __name__ == '__main__':
    unittest.main()
