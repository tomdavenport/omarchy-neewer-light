"""Deterministic theme-only choices for Complement and Alternate."""
import colorsys
import math
import re

COLOUR_KEYS = ('red', 'orange', 'yellow', 'green', 'cyan', 'blue', 'magenta',
               'bright_red', 'bright_yellow', 'bright_green', 'bright_cyan',
               'bright_blue', 'bright_magenta', 'brown',
               'color1', 'color2', 'color3', 'color4', 'color5', 'color6',
               'color9', 'color10', 'color11', 'color12', 'color13', 'color14')
TEXT_KEYS = ('selection', 'muted', 'foreground', 'dark_foreground',
             'light_foreground', 'bright_foreground', 'color7', 'color15')
BACKGROUND_KEYS = ('background', 'dark_background', 'darker_background',
                   'lighter_background', 'color0', 'color8')


def valid(values, key):
    colour = values.get(key)
    if isinstance(colour, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', colour):
        return colour.lower()
    return None


def held(cfg, roles):
    """A stopped fade holds its last sent colour until the palette changes."""
    return valid(cfg, 'held_colour') if cfg.get('held_palette') == [r['hex'] for r in roles] else None


def hsv(hex_colour):
    rgb = [int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return colorsys.rgb_to_hsv(*rgb)


def hue_distance(a, b):
    delta = abs(a - b)
    return min(delta, 1 - delta)


def rgb_distance(a, b):
    return sum((int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) ** 2
               for i in (1, 3, 5))


def shades(values, keys, excluded):
    return [(order, colour) for order, key in enumerate(keys)
            if (colour := valid(values, key)) and colour not in excluded]


def contrasting_shade(values, pair):
    for keys in (COLOUR_KEYS, TEXT_KEYS, BACKGROUND_KEYS):
        choices = shades(values, keys, set(pair))
        if choices:
            return max((min(rgb_distance(colour, other) for other in pair),
                        -order, colour) for order, colour in choices)[-1]
    return pair[0]


def complementary(values, main):
    """Use the theme hue nearest opposite Main, or its most contrasting shade."""
    main_h, main_s, _ = hsv(main)
    candidates = []
    for order, colour in shades(values, COLOUR_KEYS, {main}):
        hue, saturation, value = hsv(colour)
        if (saturation >= 0.18 and value >= 0.25 and
                (main_s < 0.18 or hue_distance(hue, main_h) >= 0.125)):
            error = hue_distance(hue, (main_h + 0.5) % 1)
            candidates.append((error if main_s >= 0.18 else 0,
                               -saturation, order, colour))
    return min(candidates)[-1] if candidates else contrasting_shade(values, (main,))


def alternate(values, main, complement):
    """Maximize the nearest hue gap from both choices, staying in the palette."""
    pair = (main, complement)
    main_h, main_s, _ = hsv(main)
    comp_h, comp_s, _ = hsv(complement)
    candidates = []
    if main_s >= 0.18 and comp_s >= 0.18:
        for order, colour in shades(values, COLOUR_KEYS, set(pair)):
            hue, saturation, value = hsv(colour)
            if saturation >= 0.18 and value >= 0.25:
                gap = min(hue_distance(hue, main_h), hue_distance(hue, comp_h))
                candidates.append((-gap, -saturation, order, colour))
    return min(candidates)[-1] if candidates else contrasting_shade(values, pair)


def validate_mix(weights):
    if (not isinstance(weights, (list, tuple)) or len(weights) != 3 or
            any(isinstance(w, bool) or not isinstance(w, (int, float)) or
                not math.isfinite(w) or not 0 <= w <= 1 for w in weights) or
            abs(sum(weights) - 1) > 0.000001):
        raise ValueError('Invalid saved colour blend. Choose a theme swatch to reset it.')
    return list(weights)


def blend(roles, weights):
    """Crossfade the three current palette colours; preserve exact endpoints."""
    weights = validate_mix(weights)
    colours = [r['hex'] for r in roles]
    return '#' + ''.join(f'{round(sum(int(c[i:i+2], 16) * w for c, w in zip(colours, weights))):02x}'
                         for i in (1, 3, 5))
