import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import light_effects as effects
import light_service as module
from light_palette import blend
import test_service as helpers


class EffectTests(unittest.IsolatedAsyncioTestCase):
    asyncTearDown = helpers.ServiceTests.asyncTearDown
    start = helpers.ServiceTests.start
    until = helpers.ServiceTests.until

    async def asyncSetUp(self):
        await helpers.ServiceTests.asyncSetUp(self)
        self.now = 0.0
        clock = patch.object(effects, 'time', SimpleNamespace(monotonic=lambda: self.now))
        self.patches.append(clock)
        clock.start()

    async def advance(self, seconds):
        self.now += seconds
        self.service.wake.set()
        await asyncio.sleep(0.025)

    async def cycle(self):
        self.service.command('mode', 'cycle')
        self.start()
        await self.until(lambda: bool(self.radio.writes))

    async def test_preview_wakes_zero_brightness_and_reclick_reapplies(self):
        self.service.cfg.update(brightness=0, last_nonzero_brightness=31,
                                last_requested_power='off')
        self.start()
        self.service.command('preview', 'alternate')
        await self.until(lambda: len(self.radio.writes) == 1)
        self.assertEqual(self.radio.writes[-1][1:], ('on', '#eeeeee', 31))
        self.service.command('preview', 'alternate')
        await self.until(lambda: len(self.radio.writes) == 2)
        self.assertEqual(self.radio.writes[-1][1:], ('on', '#eeeeee', 31))
        self.assertEqual(self.service.cfg['mode'], 'steady')

    async def test_cycle_sends_intermediate_colours_with_one_power_on(self):
        await self.cycle()
        await self.advance(6)
        self.assertNotIn(self.radio.writes[-1][2], self.colours)
        await self.advance(6)
        self.assertEqual(self.radio.writes[-1][2], '#abcdef')
        await self.advance(12)
        self.assertEqual(self.radio.writes[-1][2], '#eeeeee')
        self.assertEqual(sum(row[1] == 'on' for row in self.radio.writes), 1)
        self.assertEqual(self.radio.connections, 1)
        self.assertTrue(all(row[3] == 20 for row in self.radio.writes))

    async def test_stop_cycle_freezes_intermediate_colour(self):
        await self.cycle()
        await self.advance(6)
        held = self.radio.writes[-1][2]
        self.service.command('mode', 'steady')
        await self.advance(60)
        self.assertEqual(self.radio.writes[-1][2], held)
        self.assertIn('held_mix', self.service.cfg)
        self.assertEqual(self.service.snapshot()['hex'], held)

    async def test_preview_interrupts_fade_without_changing_brightness(self):
        self.service.cfg['brightness'] = 7
        await self.cycle()
        await self.advance(6)
        self.service.command('preview', 'alternate')
        await self.until(lambda: self.radio.writes[-1][1:] == ('on', '#eeeeee', 7))
        count = len(self.radio.writes)
        await self.advance(60)
        self.assertEqual(len(self.radio.writes), count)
        self.assertEqual(self.service.cfg['mode'], 'steady')
        self.assertNotIn('held_mix', self.service.cfg)

    async def test_off_pauses_fade_and_follow_off_releases_connection(self):
        await self.cycle()
        await self.advance(6)
        held = self.radio.writes[-1][2]
        self.service.command('off')
        await self.until(lambda: self.radio.writes[-1][1] == 'off')
        count = len(self.radio.writes)
        await self.advance(60)
        self.assertEqual(len(self.radio.writes), count)
        self.service.command('on')
        await self.until(lambda: len(self.radio.writes) > count)
        self.assertEqual(self.radio.writes[-1][2], held)
        self.service.command('follow', 'off')
        await self.until(lambda: not self.radio.connected)
        count = len(self.radio.writes)
        await self.advance(60)
        self.assertEqual(len(self.radio.writes), count)
        self.assertEqual(self.service.cfg['mode'], 'steady')

    async def test_theme_change_replaces_fade_endpoints_immediately(self):
        await self.cycle()
        await self.advance(6)
        previous = self.radio.writes[-1][2]
        self.colours[:] = ['#550000', '#ff9900', '#33ff66']
        self.service.theme_changed()
        await self.until(lambda: self.radio.writes[-1][2] != previous)
        expected = blend(self.service.roles, self.service.cycle.weights)
        self.assertEqual(self.radio.writes[-1][2], expected)
        self.assertEqual(self.radio.connections, 1)

    async def test_speed_change_preserves_colour_and_changes_transition_time(self):
        await self.cycle()
        await self.advance(6)
        held = self.radio.writes[-1][2]
        self.service.command('speed', 'fast')
        await asyncio.sleep(0.025)
        self.assertEqual(self.radio.writes[-1][2], held)
        await self.advance(1.5)
        self.assertNotEqual(self.radio.writes[-1][2], held)
        await self.advance(1.5)
        self.assertEqual(self.radio.writes[-1][2], '#abcdef')

    async def test_animation_frames_do_not_persist_settings_or_send_power(self):
        with patch.object(module, 'save') as saved:
            await self.cycle()
            baseline = saved.call_count
            for _ in range(8):
                await self.advance(0.5)
            self.assertEqual(saved.call_count, baseline)
            self.assertGreater(len(self.radio.writes), 5)
            self.assertTrue(all(row[1] == 'theme' for row in self.radio.writes[1:]))


if __name__ == '__main__':
    unittest.main()
