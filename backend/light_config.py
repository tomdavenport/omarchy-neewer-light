"""Private settings and semantic Omarchy colour roles; no Bluetooth I/O."""
import colorsys
import json
import os
import re
import time
import tomllib
from pathlib import Path
from light_palette import COLOUR_KEYS, hsv, complementary, alternate, blend, validate_mix, held

HOME = Path.home()
CONFIG = Path(os.environ.get('NEEWER_CONFIG', HOME / '.config/neewer-omarchy/config.json'))
STATE = Path(os.environ.get('NEEWER_STATE', HOME / '.local/state/neewer-omarchy'))
THEME = Path(os.environ.get('NEEWER_THEME', HOME / '.local/state/omarchy/current'))
SOCKET = Path(os.environ.get('XDG_RUNTIME_DIR', STATE)) / 'neewer-light.sock'
ROLES = ('accent', 'complementary', 'alternate')
DEFAULTS = dict(address='', model='RGB1', protocol='infinity', brightness=20,
                follow=True, role='accent', setup_complete=False, power='unknown',
                mode='steady', speed='slow', last_nonzero_brightness=20,
                theme_fade='gentle', off_when_locked=False, off_on_shutdown=False)


def valid_address(value):
    return bool(re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}', value))


def rgb1_name(name):
    return '20200015' in (name or '') or bool(re.search(r'\bRGB[- ]?1\b', name or '', re.I))


def load():
    saved = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    cfg = DEFAULTS | saved
    if cfg['address'] and not valid_address(cfg['address']):
        raise ValueError('The saved light address is invalid. Open Light setup.')
    if cfg['protocol'] not in ('infinity', 'legacy'):
        raise ValueError('The saved light protocol is invalid.')
    if not isinstance(cfg['brightness'], int) or not 0 <= cfg['brightness'] <= 100:
        raise ValueError('Brightness must be between 0 and 100.')
    if 'last_nonzero_brightness' not in saved and cfg['brightness'] > 0:
        cfg['last_nonzero_brightness'] = cfg['brightness']
    if (not isinstance(cfg['last_nonzero_brightness'], int) or
            not 1 <= cfg['last_nonzero_brightness'] <= 100):
        raise ValueError('Last nonzero brightness must be between 1 and 100.')
    if 'held_mix' in cfg:
        cfg['held_mix'] = validate_mix(cfg['held_mix'])
    if cfg['mode'] not in ('steady', 'cycle'):
        raise ValueError('Light mode must be steady or cycle.')
    if cfg['speed'] not in ('slow', 'medium', 'fast'):
        raise ValueError('Cycle speed must be slow, medium or fast.')
    if cfg['theme_fade'] not in ('off', 'quick', 'gentle'):
        raise ValueError('Theme fade must be off, quick or gentle.')
    if any(not isinstance(cfg[key], bool) for key in ('off_when_locked', 'off_on_shutdown')):
        raise ValueError('Automatic power settings must be on or off.')
    old_roles = {'secondary': 'complementary', 'neutral': 'accent'}
    cfg['role'] = old_roles.get(cfg['role'], cfg['role'])
    if cfg['role'] not in ROLES:
        cfg['role'] = 'accent'
    if 'last_role' in cfg:
        cfg['last_role'] = old_roles.get(cfg['last_role'], cfg['last_role'])
    if 'setup_complete' not in saved:
        cfg['setup_complete'] = bool(cfg['address'] and cfg.get('last_sent'))
    return cfg


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2) + '\n')
    tmp.chmod(0o600)
    tmp.replace(path)


def save(cfg):
    write_json(CONFIG, cfg)


def palette():
    values = tomllib.loads((THEME / 'theme/colors.toml').read_text())

    def first(*keys):
        for key in keys:
            value = values.get(key)
            if isinstance(value, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                return value.lower()
        raise ValueError('This theme has no usable colour palette.')

    main = first('accent', 'blue', 'color4', 'foreground')
    complement = complementary(values, main)
    roles = [dict(id='accent', label='Main', hex=main),
             dict(id='complementary', label='Complement', hex=complement),
             dict(id='alternate', label='Alternate', hex=alternate(values, main, complement))]
    return (THEME / 'theme.name').read_text().strip().replace('-', ' ').title(), roles


def selected(cfg):
    theme, roles = palette()
    colour = next(r['hex'] for r in roles if r['id'] == cfg['role'])
    if cfg.get('mode') == 'steady' and cfg.get('held_mix') is not None:
        colour = held(cfg, roles) or blend(roles, cfg['held_mix'])
    return theme, roles, colour


def frame(opcode, payload):
    packet = bytes([0x78, opcode, len(payload), *payload])
    return packet + bytes([sum(packet) & 255])


def packet(cfg, action, colour):
    rgb = [int(colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    hue, saturation, _ = colorsys.rgb_to_hsv(*rgb)
    hue = round(hue * 360) % 360
    opcode = 0x81 if action in ('on', 'off') else 0x86
    data = ([1 if action == 'on' else 2] if opcode == 0x81 else
            [hue & 255, hue >> 8, round(saturation * 100), cfg['brightness']])
    if cfg['protocol'] == 'infinity':
        data = list(bytes.fromhex(cfg['address'].replace(':', ''))) + [opcode] + data
        opcode = 0x8D if opcode == 0x81 else 0x8F
    return frame(opcode, data)


def sent(cfg, colour, theme, action):
    cfg['last_sent'] = time.strftime('%Y-%m-%d %H:%M:%S')
    cfg['power'] = 'unknown'
    if action != 'off':
        cfg.update(last_colour=colour, last_theme=theme, last_role=cfg['role'])
    save(cfg)
