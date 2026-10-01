"""Focused tests for the three Omarchy theme colours and saved preferences."""
import json
import re
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

import light_config as config


class PaletteTripletTests(unittest.TestCase):
    def test_opposite_named_hue_wins(self):
        values = dict(accent='#ff0000', red='#ff0000', green='#00ff00',
                      blue='#0000ff', cyan='#00ffff', orange='#ff8800')
        self.assertEqual(config.complementary(values, values['accent']), '#00ffff')

    def test_monochrome_fallback_is_distinct_and_deterministic(self):
        values = dict(accent='#888888', red='#bbbbbb', blue='#555555',
                      cyan='#eeeeee', magenta='#777777')
        pair = config.complementary(values, values['accent'])
        self.assertEqual(pair, '#eeeeee')
        self.assertEqual(config.complementary(values, values['accent']), pair)
        self.assertIn(pair, values.values())

    def test_no_alternative_returns_main(self):
        self.assertEqual(config.complementary({'accent': '#777777'}, '#777777'),
                         '#777777')

    def test_alternate_maximizes_gap_from_main_and_complement(self):
        values = dict(accent='#ff0000', cyan='#00ffff', green='#00ff00',
                      blue='#0000ff', orange='#ff8800')
        self.assertEqual(config.alternate(values, '#ff0000', '#00ffff'), '#00ff00')

    def test_monochrome_alternate_stays_in_palette(self):
        values = dict(accent='#888888', red='#bbbbbb', blue='#555555', cyan='#eeeeee')
        third = config.alternate(values, '#888888', '#eeeeee')
        self.assertIn(third, ('#bbbbbb', '#555555'))
        self.assertEqual(third, config.alternate(values, '#888888', '#eeeeee'))

    def test_stock_palettes_use_real_distinct_hues_when_available(self):
        paths = sorted(Path('/usr/share/omarchy/themes').glob('*/colors.toml'))
        if not paths:
            self.skipTest('No installed Omarchy palettes on this machine.')
        for path in paths:
            with self.subTest(theme=path.parent.name):
                values = tomllib.loads(path.read_text())
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    (root / 'theme').symlink_to(path.parent, target_is_directory=True)
                    (root / 'theme.name').write_text(path.parent.name)
                    with patch.object(config, 'THEME', root):
                        _, roles = config.palette()
                self.assertEqual([role['id'] for role in roles],
                                 ['accent', 'complementary', 'alternate'])
                main, other, third = (role['hex'] for role in roles)
                self.assertEqual(main, values['accent'].lower())
                self.assertRegex(other, r'^#[0-9a-f]{6}$')
                self.assertNotEqual(main, other)
                self.assertEqual(len({main, other, third}), 3)
                main_h, main_s, _ = config.hsv(main)
                eligible = []
                for key in config.COLOUR_KEYS:
                    colour = values.get(key)
                    if not isinstance(colour, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', colour):
                        continue
                    hue, saturation, value = config.hsv(colour)
                    separation = abs(hue - main_h)
                    if (colour.lower() != main and saturation >= 0.18 and value >= 0.25
                            and (main_s < 0.18 or min(separation, 1 - separation) >= 0.125)):
                        eligible.append(colour.lower())
                self.assertIn(other, [str(value).lower() for value in values.values()])
                self.assertIn(third, [str(value).lower() for value in values.values()])
                if eligible:
                    self.assertIn(other, eligible)

    def test_old_roles_migrate_without_changing_main_id(self):
        for old, expected in [('accent', 'accent'), ('secondary', 'complementary'),
                              ('neutral', 'accent')]:
            with self.subTest(old=old), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'config.json'
                path.write_text(json.dumps(dict(role=old, last_role=old)))
                with patch.object(config, 'CONFIG', path):
                    cfg = config.load()
                self.assertEqual(cfg['role'], expected)
                self.assertEqual(cfg['last_role'], expected)

    def test_effect_defaults_and_saved_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'config.json'
            path.write_text(json.dumps(dict(brightness=72)))
            with patch.object(config, 'CONFIG', path):
                cfg = config.load()
            self.assertEqual((cfg['mode'], cfg['speed'], cfg['last_nonzero_brightness']),
                             ('steady', 'slow', 72))
            path.write_text(json.dumps(dict(mode='cycle', speed='fast',
                                            brightness=0, last_nonzero_brightness=42,
                                            role='alternate')))
            with patch.object(config, 'CONFIG', path):
                cfg = config.load()
            self.assertEqual((cfg['mode'], cfg['speed'], cfg['last_nonzero_brightness'], cfg['role']),
                             ('cycle', 'fast', 42, 'alternate'))

    def test_invalid_effect_values_are_rejected(self):
        for field, value in [('mode', 'blink'), ('speed', 'instant'),
                             ('last_nonzero_brightness', 0)]:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'config.json'
                path.write_text(json.dumps({field: value}))
                with patch.object(config, 'CONFIG', path), self.assertRaises(ValueError):
                    config.load()


if __name__ == '__main__':
    unittest.main()
