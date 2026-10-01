import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import light_transition as transition
from light_config import packet
import test_service as helpers


class TransitionTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        clock = patch.object(transition, 'time', SimpleNamespace(monotonic=lambda: self.now))
        clock.start()
        self.addCleanup(clock.stop)
        self.old = [dict(id='accent', hex='#000000')]
        self.new = [dict(id='accent', hex='#ffffff')]
        self.fade = transition.ThemeTransition('old', self.old)

    def render(self, target='#ffffff', source='#000000', eligible=True):
        return self.fade.render('new', self.new, target, source, eligible)

    def test_matches_omarchy_cubic_curve_and_exact_deadline(self):
        self.assertEqual(self.render(), ('#000000', True))
        for elapsed, colour in [(0.105, '#101010'), (0.210, '#808080'), (0.315, '#efefef')]:
            self.now = elapsed
            self.assertEqual(self.render(), (colour, True))
        self.now = 0.410
        self.assertAlmostEqual(self.fade.wait_seconds(), 0.010)
        self.now = 0.420
        self.assertEqual(self.render(), ('#ffffff', True))
        self.assertFalse(self.fade.active)
        self.assertEqual(self.render(), ('#ffffff', False))

    def test_duplicate_palette_keeps_deadline_and_cycle_target_can_move(self):
        self.render()
        self.now = 0.210
        self.assertEqual(self.render('#ff0000'), ('#800000', True))
        self.assertEqual(self.fade.started, 0.0)
        self.now = 0.420
        self.assertEqual(self.render('#00ff00'), ('#00ff00', True))

    def test_retarget_starts_at_last_completed_write(self):
        self.render()
        self.now = 0.25
        latest = [dict(id='accent', hex='#112233')]
        self.assertEqual(self.fade.render('latest', latest, '#112233', '#556677', True),
                         ('#556677', True))
        self.assertEqual(self.fade.started, 0.25)

    def test_off_reconnect_and_explicit_preview_cancel_old_fade(self):
        self.assertEqual(self.render(eligible=False), ('#ffffff', False))
        self.assertFalse(self.fade.active)
        self.fade.cancel('old', self.old)
        self.render()
        self.fade.cancel('new', self.new)
        self.assertEqual(self.render('#ff0000'), ('#ff0000', False))
        self.assertIsNone(self.fade.wait_seconds())


class TransitionServiceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = helpers.ServiceTests.asyncSetUp
    asyncTearDown = helpers.ServiceTests.asyncTearDown
    start = helpers.ServiceTests.start
    until = helpers.ServiceTests.until

    async def begin_fade(self):
        self.start()
        await self.until(lambda: bool(self.radio.writes))
        self.theme, self.colours[0] = 'Second', '#ff2200'
        self.service.theme_changed()
        await self.until(lambda: self.service.transition.active)

    async def test_preview_interrupts_theme_fade_immediately(self):
        self.service.cfg['brightness'] = 37
        await self.begin_fade()
        self.service.command('preview', 'alternate')
        await self.until(lambda: self.radio.writes[-1][1:] == ('on', '#eeeeee', 37))
        count = len(self.radio.writes)
        await asyncio.sleep(0.46)
        self.assertEqual(len(self.radio.writes), count)
        self.assertFalse(self.service.transition.active)

    async def test_off_interrupts_theme_fade_and_stays_off(self):
        await self.begin_fade()
        self.service.command('off')
        await self.until(lambda: self.radio.writes[-1][1] == 'off')
        count = len(self.radio.writes)
        self.theme, self.colours[0] = 'Third', '#00ff22'
        self.service.theme_changed()
        await asyncio.sleep(0.46)
        self.assertEqual(len(self.radio.writes), count)
        self.assertFalse(self.service.transition.active)

    async def test_overlapping_theme_uses_latest_actual_colour_and_hook_does_not_restart(self):
        await self.begin_fade()
        await self.until(lambda: len(self.radio.writes) > 2)
        actual = self.service.cfg['last_colour']
        self.theme, self.colours[0] = 'Third', '#22ff00'
        self.service.theme_changed()
        await self.until(lambda: self.service.transition.source == actual)
        started = self.service.transition.started
        self.service.command('hook')
        await asyncio.sleep(0.02)
        self.assertEqual(self.service.transition.started, started)
        await self.until(lambda: not self.service.transition.active)
        self.assertEqual(packet(self.service.cfg, 'theme', self.radio.writes[-1][2]),
                         packet(self.service.cfg, 'theme', '#22ff00'))
        self.assertEqual(self.radio.connections, 1)
        self.assertTrue(all(row[1] == 'theme' for row in self.radio.writes))

    async def test_delayed_bluetooth_write_skips_missed_frames_and_stays_serial(self):
        await self.begin_fade()
        self.radio.write_gate = asyncio.Event()
        await self.until(lambda: self.radio.started == 2)
        await asyncio.sleep(0.46)
        self.assertEqual(self.radio.started, 2)
        self.radio.write_gate.set()
        await self.until(lambda: self.radio.writes[-1][2] == '#ff2200')
        self.assertEqual(len(self.radio.writes), 3)
        self.assertEqual(self.radio.connections, 1)

    async def test_reconnect_skips_transition_and_reads_latest_palette(self):
        await self.begin_fade()
        self.radio.connected = False
        self.theme, self.colours[0] = 'Latest', '#4400ff'
        self.service.wake.set()
        await self.until(lambda: self.radio.connections == 2)
        self.assertEqual(self.radio.writes[-1][2], '#4400ff')
        self.assertFalse(self.service.transition.active)
