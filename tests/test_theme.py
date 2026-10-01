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
    async def test_background_event_starts_420ms_fade_on_warm_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'theme').mkdir()
            colours = root / 'theme/colors.toml'
            colours.write_text('accent="#112233"\norange="#dd7733"\nforeground="#eeeeee"\n')
            (root / 'theme.name').write_text('first')
            cfg = config.DEFAULTS | dict(address='00:11:22:33:44:55', setup_complete=True, theme_fade='quick')
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
                    (root / 'theme.name').write_text('second')
                    await asyncio.sleep(0.05)
                    self.assertEqual(len(radio.writes), 1)
                    self.assertEqual(light.theme, 'First')
                    started = time.monotonic()
                    (root / 'background').symlink_to('wallpaper.png')
                    async with asyncio.timeout(1):
                        while len(radio.writes) == 1:
                            await asyncio.sleep(0.002)
                    first_frame = time.monotonic() - started
                    self.assertLess(first_frame, 0.2)
                    self.assertNotEqual(radio.writes[-1][2], '#445566')
                    async with asyncio.timeout(1):
                        while light.transition.active:
                            await asyncio.sleep(0.002)
                    self.assertEqual(config.packet(cfg, 'theme', radio.writes[-1][2]),
                                     config.packet(cfg, 'theme', '#445566'))
                    elapsed = (time.monotonic() - started) * 1000
                    self.assertGreaterEqual(elapsed, 410)
                    self.assertLess(elapsed, 750)
                    self.assertEqual(radio.connections, 1)
                    print(f'Background event → final simulated colour: {elapsed:.1f} ms; one connection')
                finally:
                    watcher.close()
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

    async def test_theme_without_background_has_bounded_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root, calls = Path(directory), []
            watcher = ThemeWatch(root, lambda: calls.append(time.monotonic()))
            try:
                started = time.monotonic()
                (root / 'theme.name').write_text('first')
                async with asyncio.timeout(1):
                    while not calls:
                        await asyncio.sleep(0.002)
                self.assertGreaterEqual(calls[0] - started, 0.14)
                self.assertLess(calls[0] - started, 0.3)
                (root / 'background').symlink_to('late.png')
                await asyncio.sleep(0.2)
                self.assertEqual(len(calls), 1)
            finally:
                watcher.close()

    async def test_rapid_theme_and_replaced_background_use_latest_palette_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root, calls = Path(directory), []
            (root / 'background').symlink_to('old.png')
            watcher = ThemeWatch(root, lambda: calls.append((root / 'theme.name').read_text()))
            try:
                (root / 'theme.name').write_text('first')
                await asyncio.sleep(0.02)
                (root / 'theme.name').write_text('second')
                await asyncio.sleep(0.02)
                (root / 'next-background').symlink_to('new.png')
                (root / 'next-background').replace(root / 'background')
                await asyncio.sleep(0.2)
                self.assertEqual(calls, ['second'])
                (root / 'background').unlink()
                (root / 'background').symlink_to('background-only.png')
                await asyncio.sleep(0.2)
                self.assertEqual(calls, ['second'])
            finally:
                watcher.close()

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
