"""Pure, deterministic coverage for PaletteCycle timing and fade state."""
import unittest
from unittest.mock import patch

import light_effects as effects


ROLES = [
    {'id': 'accent', 'hex': '#ff0000'},
    {'id': 'complementary', 'hex': '#0000ff'},
    {'id': 'alternate', 'hex': '#00ff00'},
]


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class FadeMathTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.time = patch.object(effects.time, 'monotonic', self.clock)
        self.time.start()
        self.cycle = effects.PaletteCycle()
        self.cfg = dict(mode='cycle', speed='fast', role='accent', brightness=37,
                        last_requested_power='on')
        self.cycle.reset(self.cfg)

    def tearDown(self):
        self.time.stop()

    def render(self):
        return self.cycle.render(self.cfg, ROLES)

    def test_exact_start_preserves_selected_colour_and_brightness(self):
        active, colour, animated = self.render()
        self.assertEqual(colour, '#ff0000')
        self.assertTrue(animated)
        self.assertEqual(active['brightness'], 37)
        self.assertEqual(self.cycle.weights, [1.0, 0.0, 0.0])

    def test_smooth_intermediate_progress(self):
        self.clock.now = 1.5
        _, colour, _ = self.render()
        self.assertEqual(colour, '#800080')
        self.assertEqual(self.cycle.weights, [0.5, 0.5, 0.0])

    def test_endpoints_wrap_exactly_through_all_roles(self):
        for now, role, colour in ((3.0, 'complementary', '#0000ff'),
                                  (6.0, 'alternate', '#00ff00'),
                                  (9.0, 'accent', '#ff0000')):
            self.clock.now = now
            active, rendered, _ = self.render()
            self.assertEqual((active['role'], rendered), (role, colour))
            self.assertEqual(self.cycle.weights, effects._one_hot(role))

    def test_large_clock_jump_skips_frames_and_cycles_without_a_queue(self):
        self.clock.now = 100.0
        _, colour, _ = self.render()
        expected = effects._eased(1 / 3)
        self.assertEqual(self.cycle.role, 'accent')
        self.assertAlmostEqual(self.cycle.weights[1], expected)
        self.assertEqual(colour, effects.light_palette.blend(ROLES, self.cycle.weights))
        frozen = list(self.cycle.weights)
        self.render()
        self.assertEqual(self.cycle.weights, frozen)
        self.assertLessEqual(self.cycle.wait_seconds(self.cfg), effects.FRAME_SECONDS)

    def test_speed_reset_preserves_current_weights(self):
        self.clock.now = 1.5
        self.render()
        before = list(self.cycle.weights)
        self.cfg['speed'] = 'slow'
        self.cycle.reset(self.cfg, preserve=True)
        self.render()
        self.assertEqual(self.cycle.weights, before)

    def test_off_pauses_weights_and_on_reset_resumes_without_jump(self):
        self.clock.now = 1.0
        self.render()
        before = list(self.cycle.weights)
        self.cfg['last_requested_power'] = 'off'
        self.clock.now = 100.0
        _, _, animated = self.render()
        self.assertFalse(animated)
        self.assertEqual(self.cycle.weights, before)
        self.assertIsNone(self.cycle.wait_seconds(self.cfg))
        self.cfg['last_requested_power'] = 'on'
        self.cycle.reset(self.cfg, preserve=True)
        self.render()
        self.assertEqual(self.cycle.weights, before)


if __name__ == '__main__':
    unittest.main()
