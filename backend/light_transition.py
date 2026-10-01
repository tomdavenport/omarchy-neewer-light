"""Short theme-change fades layered over the existing steady/Cycle colour."""
import time

# Omarchy 4's Background.qml: NumberAnimation, 420 ms, Easing.InOutCubic.
THEME_FADE_SECONDS = 0.420
FADE_FRAME_SECONDS = 0.05


def palette_key(theme, roles):
    return theme, tuple((role['id'], role['hex']) for role in roles)


def interpolate(source, target, progress):
    eased = 4 * progress ** 3 if progress < 0.5 else 1 - (-2 * progress + 2) ** 3 / 2
    return '#' + ''.join(f'{round(int(source[i:i+2], 16) * (1-eased) + int(target[i:i+2], 16) * eased):02x}'
                         for i in (1, 3, 5))


class ThemeTransition:
    def __init__(self, theme, roles):
        self.key = palette_key(theme, roles)
        self.started = None
        self.source = None

    @property
    def active(self):
        return self.started is not None

    def cancel(self, theme, roles):
        self.key = palette_key(theme, roles)
        self.started, self.source = None, None

    def render(self, theme, roles, target, last_colour, eligible):
        """Use the last completed hardware write; never replay old fade frames."""
        key = palette_key(theme, roles)
        if key != self.key:
            self.cancel(theme, roles)
            if eligible and last_colour and last_colour != target:
                self.started, self.source = time.monotonic(), last_colour
        if not eligible:
            self.cancel(theme, roles)
        if not self.active:
            return target, False
        progress = max(0.0, (time.monotonic() - self.started) / THEME_FADE_SECONDS)
        if progress >= 1.0:
            self.cancel(theme, roles)
            return target, True  # The exact final colour still needs a write.
        return interpolate(self.source, target, progress), True

    def wait_seconds(self, default=None):
        if not self.active:
            return default
        remaining = self.started + THEME_FADE_SECONDS - time.monotonic()
        return min(FADE_FRAME_SECONDS, max(0.001, remaining))
