import asyncio
import unittest
from unittest.mock import patch
import light_service as module
from light_config import DEFAULTS


class FakeRadio:
    def __init__(self):
        self.connected, self.address = False, ''
        self.connections, self.writes = 0, []
        self.gate = None
        self.fail_connect = False
        self.write_gate, self.started = None, 0

    async def connect(self, cfg):
        self.connections += 1
        if self.gate:
            await self.gate.wait()
        if self.fail_connect:
            raise ConnectionError('test disconnect')
        self.address, self.connected = cfg['address'], True

    async def disconnect(self):
        self.connected = False

    async def write(self, cfg, action, colour):
        self.started += 1
        if self.write_gate:
            await self.write_gate.wait()
        self.writes.append((cfg['address'], action, colour, cfg['brightness']))


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.cfg = DEFAULTS | dict(address='00:11:22:33:44:55', setup_complete=True,
                                   last_requested_power='on', theme_fade='quick')
        self.colours = ['#123456', '#abcdef', '#eeeeee']
        self.theme = 'First'
        self.radio = FakeRadio()
        def palette(cfg):
            roles = [dict(id=role, label=role.title(), hex=colour) for role, colour in
                     zip(('accent', 'complementary', 'alternate'), self.colours)]
            return self.theme, roles, next(r['hex'] for r in roles if r['id'] == cfg['role'])
        self.patches = [patch.object(module, 'load', lambda: dict(self.cfg)),
            patch.object(module, 'Radio', lambda _: self.radio),
            patch.object(module, 'selected', palette), patch.object(module, 'save'),
            patch.object(module, 'write_json'), patch('light_commands.selected', palette),
            patch('light_commands.save')]
        for item in self.patches:
            item.start()
        self.service = module.LightService()
        self.task = None

    async def asyncTearDown(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        for task in self.service.tasks:
            task.cancel()
        for item in reversed(self.patches):
            item.stop()

    def start(self):
        self.task = asyncio.create_task(self.service.run())

    async def until(self, check):
        async with asyncio.timeout(1):
            while not check():
                await asyncio.sleep(0.002)

    async def test_warm_theme_role_and_duplicate_hook(self):
        self.start()
        await self.until(lambda: len(self.radio.writes) == 1)
        self.service.command('role', 'complementary')
        await self.until(lambda: len(self.radio.writes) == 2)
        self.assertEqual(self.radio.writes[-1][2], '#abcdef')
        self.colours[1], self.theme = '#fedcba', 'Second'
        self.service.theme_changed()
        await self.until(lambda: self.radio.writes[-1][2] == '#fedcba')
        self.assertEqual(self.radio.writes[-1][2], '#fedcba')
        self.assertEqual(self.radio.connections, 1)
        count = len(self.radio.writes)
        self.service.command('hook')
        await asyncio.sleep(0.02)
        self.assertEqual(len(self.radio.writes), count)
        self.assertEqual(self.service.cfg['role'], 'complementary')

    async def test_latest_theme_wins_during_connect(self):
        self.radio.gate = asyncio.Event()
        self.start()
        await self.until(lambda: self.radio.connections == 1)
        for colour in ('#111111', '#222222', '#333333'):
            self.colours[0] = colour
            self.service.theme_changed()
        self.radio.gate.set()
        await self.until(lambda: bool(self.radio.writes))
        self.assertEqual([row[2] for row in self.radio.writes], ['#333333'])

    async def test_off_stays_off_until_explicit_on(self):
        self.start()
        await self.until(lambda: bool(self.radio.writes))
        self.service.command('off')
        await self.until(lambda: self.radio.writes[-1][1] == 'off')
        count = len(self.radio.writes)
        self.service.command('role', 'accent')
        self.service.theme_changed()
        self.service.command('hook')
        self.service.command('theme')
        await asyncio.sleep(0.02)
        self.assertEqual(len(self.radio.writes), count)
        self.service.command('on')
        await self.until(lambda: self.radio.writes[-1][1] == 'on')
        self.assertEqual(self.radio.writes[-1][2], '#123456')

    async def test_follow_off_during_failed_connect_cancels_colour(self):
        self.radio.gate = asyncio.Event()
        self.radio.fail_connect = True
        self.start()
        await self.until(lambda: self.radio.connections == 1)
        self.service.command('follow', 'off')
        self.radio.gate.set()
        await self.until(lambda: self.service.message == 'Theme following is off.')
        self.assertEqual(self.radio.connections, 1)
        self.assertEqual(self.radio.writes, [])

    async def test_new_setup_requires_test_and_confirmation(self):
        self.service.cfg.update(address='', setup_complete=False)
        self.service.dirty = False
        self.service.devices = [dict(address=self.cfg['address'], label='RGB1')]
        self.start()
        self.service.command('select', self.cfg['address'])
        self.service.command('hook')
        self.service.theme_changed()
        await asyncio.sleep(0.02)
        self.assertEqual(self.radio.connections, 0)
        with self.assertRaises(ValueError):
            self.service.command('confirm')
        self.service.command('test')
        await self.until(lambda: self.service.test_success)
        self.assertEqual(self.radio.writes[-1][1], 'test')
        self.service.command('confirm')
        await self.until(lambda: self.radio.connected)
        self.assertTrue(self.service.cfg['setup_complete'])

    async def test_bad_palette_or_save_never_commits_settings(self):
        before = dict(self.service.cfg)
        for target in ('light_commands.selected', 'light_commands.save'):
            with patch(target, side_effect=OSError('not available')):
                with self.assertRaises(OSError):
                    self.service.command('brightness', '35')
            self.assertEqual(self.service.cfg, before)

    async def test_selection_during_failure_never_sends_to_new_unconfirmed_light(self):
        self.radio.gate = asyncio.Event()
        self.radio.fail_connect = True
        self.start()
        await self.until(lambda: self.radio.connections == 1)
        other = '00:11:22:33:44:66'
        self.service.devices = [dict(address=other, label='Other RGB1')]
        self.service.command('select', other)
        self.radio.gate.set()
        await self.until(lambda: self.service.stage == 'offline')
        await asyncio.sleep(0.02)
        self.assertEqual(self.radio.connections, 1)
        self.assertEqual(self.radio.writes, [])
        self.assertFalse(self.service.cfg['setup_complete'])

    async def test_new_role_during_write_is_not_lost(self):
        self.start()
        await self.until(lambda: bool(self.radio.writes))
        self.radio.write_gate = asyncio.Event()
        self.service.command('role', 'complementary')
        await self.until(lambda: self.radio.started == 2)
        self.service.command('role', 'accent')
        self.radio.write_gate.set()
        await self.until(lambda: len(self.radio.writes) == 3)
        self.assertEqual(self.radio.writes[-1][2], '#123456')
        self.assertEqual(self.service.cfg['last_role'], 'accent')


if __name__ == '__main__':
    unittest.main()
