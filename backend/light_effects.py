"""Palette effects with bounded, in-memory animation state."""
import time

import light_palette
from light_config import ROLES

SPEEDS = {'slow': 12.0, 'medium': 6.0, 'fast': 3.0}
FRAME_SECONDS = 0.1


def _mix(value):
    """Return a valid saved three-role mix without surfacing config errors here."""
    try:
        return light_palette.validate_mix(value)
    except ValueError:
        return None


def _one_hot(role, role_ids=ROLES):
    return [1.0 if item == role else 0.0 for item in role_ids]


def _eased(progress):
    """Smoothstep, preserving exact endpoints for hardware colour matching."""
    return progress * progress * (3.0 - 2.0 * progress)


class PaletteCycle:
    """Crossfade through semantic palette roles without queuing missed frames."""
    def __init__(self):
        self.role = None
        self.weights = [1.0, 0.0, 0.0]
        self.started = None
        self.deadline = 0.0
        self._leg_start = list(self.weights)

    def reset(self, cfg, preserve=False):
        """Begin a leg now; preserving makes speed and power changes seamless."""
        requested = cfg.get('role')
        if not preserve or self.role not in ROLES:
            self.role = requested if requested in ROLES else ROLES[0]
            self.weights = _mix(cfg.get('held_mix')) or _one_hot(self.role)
        self._leg_start = list(self.weights)
        self.started = time.monotonic()
        self.deadline = self.started + SPEEDS.get(cfg.get('speed'), SPEEDS['slow'])

    def render(self, cfg, roles):
        """Return active config, current colour, and whether this is an animation."""
        active = dict(cfg)
        role_ids = [item.get('id') for item in roles]
        if len(role_ids) != len(ROLES) or set(role_ids) != set(ROLES):
            role_ids = list(ROLES)

        if cfg.get('mode', 'steady') != 'cycle':
            self.role = cfg.get('role') if cfg.get('role') in role_ids else role_ids[0]
            weights = _mix(cfg.get('held_mix'))
            colour = (light_palette.held(cfg, roles) or light_palette.blend(roles, weights)) if weights else next(
                item['hex'] for item in roles if item['id'] == self.role)
            return active, colour, False

        if self.role not in role_ids or self.started is None:
            self.reset(cfg)

        active['role'] = self.role
        if cfg.get('last_requested_power') == 'off':
            return active, light_palette.blend(roles, self.weights), False

        now = time.monotonic()
        duration = SPEEDS.get(cfg.get('speed'), SPEEDS['slow'])
        elapsed = max(0.0, now - self.started)
        completed = int(elapsed // duration)
        if completed:
            current = role_ids.index(self.role)
            self.role = role_ids[(current + completed) % len(role_ids)]
            self.weights = _one_hot(self.role, role_ids)
            self._leg_start = list(self.weights)
            self.started += completed * duration
            elapsed -= completed * duration
            active['role'] = self.role

        progress = min(1.0, elapsed / duration)
        target = _one_hot(role_ids[(role_ids.index(self.role) + 1) % len(role_ids)],
                          role_ids)
        eased = _eased(progress)
        self.weights = [start + (end - start) * eased
                        for start, end in zip(self._leg_start, target)]
        self.deadline = self.started + duration
        return active, light_palette.blend(roles, self.weights), True

    def wait_seconds(self, cfg):
        """Pace frames at 10 Hz on Slow, 20 Hz otherwise; never queue catch-up."""
        if cfg.get('mode', 'steady') != 'cycle' or cfg.get('last_requested_power') == 'off':
            return None
        return FRAME_SECONDS / 2 if cfg.get('speed') in ('medium', 'fast') else FRAME_SECONDS


def illuminate(cfg):
    if cfg['brightness'] == 0:
        cfg['brightness'] = cfg.get('last_nonzero_brightness', 20) or 20
    cfg['last_requested_power'] = 'on'
