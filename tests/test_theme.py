import asyncio
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import light_config as config
import light_service as service
from theme_watch import ThemeWatch
from test_service import FakeRadio


class ThemeTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_file_event_updates_warm_light_under_200ms(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'theme').mkdir()
            colours = root / 'theme/colors.toml'
            colours.write_text('accent="#112233"\norange="#dd7733"\nforeground="#eeeeee"\n')
            (root / 'theme.name').write_text('first')
            cfg = config.DEFAULTS | dict(address='00:11:22:33:44:55', setup_complete=True)
            radio = FakeRadio()
            with patch.object(config, 'THEME', root), patch.object(service, 'load', lambda: cfg), \
                 patch.object(service, 'Radio', lambda _: radio), patch.object(service, 'save'), \
                 patch.object(service, 'write_json'):
                light = service.LightService()
                watcher = ThemeWatch(root, light.theme_changed)
                task = asyncio.create_task(light.run())
                try:
                    async with asyncio.timeout(1):
                        while not radio.writes:
                            await asyncio.sleep(0.002)
                    colours.write_text('accent="#445566"\norange="#ffaa55"\nforeground="#eeeeee"\n')
                    started = time.monotonic()
                    (root / 'theme.name').write_text('second')
                    async with asyncio.timeout(1):
                        while radio.writes[-1][2] != '#445566':
                            await asyncio.sleep(0.002)
                    elapsed = (time.monotonic() - started) * 1000
                    self.assertLess(elapsed, 200)
                    self.assertEqual(radio.connections, 1)
                    print(f'File change → simulated BLE write: {elapsed:.1f} ms; one connection')
                finally:
                    watcher.close()
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def test_all_installed_themes_offer_three_valid_roles(self):
        paths = list(Path('/usr/share/omarchy/themes').glob('*/colors.toml'))
        current = config.THEME / 'theme/colors.toml'
        if current.exists():
            paths.append(current)
        if not paths:
            self.skipTest('No installed Omarchy palettes on this machine.')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'theme').mkdir()
            (root / 'theme.name').write_text('test')
            for source in paths:
                (root / 'theme/colors.toml').write_text(source.read_text())
                with patch.object(config, 'THEME', root):
                    _, roles = config.palette()
                self.assertEqual([r['id'] for r in roles], ['accent', 'complementary', 'alternate'])
                for role in roles:
                    self.assertRegex(role['hex'], '^#[0-9a-f]{6}$')
            print(f'Palette mapping: {len(paths)} installed/current themes passed')

    async def test_rgb1_packet_layout_and_checksum(self):
        cfg = config.DEFAULTS | dict(address='00:11:22:33:44:55')
        self.assertEqual(config.packet(cfg, 'theme', '#8be9fd').hex(), '788f0b00112233445586bf002d1497')
        self.assertEqual(config.packet(cfg, 'on', '#8be9fd').hex(), '788d0800112233445581018e')
        self.assertEqual(config.packet(cfg, 'off', '#8be9fd').hex(), '788d0800112233445581028f')


if __name__ == '__main__':
    unittest.main()
