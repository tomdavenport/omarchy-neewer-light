"""Configuration, status snapshots and palette acceptance for the light service."""
import asyncio
import time
from light_config import STATE, load, selected, write_json
from light_ble import Radio, discover
from light_effects import PaletteCycle
from light_transition import ThemeTransition
from light_power import PowerPolicy

KEEPALIVE_SECONDS = 5.0


class LightState:
    def __init__(self, load=load, radio=Radio, selected=selected, write_json=write_json):
        self.selected, self.write_json = selected, write_json
        self.cfg = load()
        self.instance, self.revision = time.monotonic_ns() // 1000000, 0
        self.power = PowerPolicy(self)
        self.power_settings_changed = lambda: None
        self.power_status = dict(lock_monitor='starting', shutdown_monitor='starting')
        self.cycle = PaletteCycle()
        self.wake = asyncio.Event()
        self.radio = radio(self.wake.set)
        self.stage, self.message = 'offline', 'Starting light controls…'
        self.scanning, self.devices, self.test_success = False, [], False
        self.dirty, self.force, self.pending_power = self.cfg['follow'] and self.cfg['setup_complete'], False, None
        self.last_signature, self.triggered_at, self.theme_latency_ms = None, None, None
        self.sent_count = 0
        self.keepalive_count, self.connection_count = 0, 0
        self.last_activity, self.connected_at = 0.0, None
        self.last_keepalive = None
        self.last_error, self.published_at = '', 0.0
        self.generation, self.probe_requested = 0, False
        self.theme, self.roles, self.colour = self.selected(self.cfg)
        self.transition = ThemeTransition(self.theme, self.roles)
        self.tasks = set()

    def snapshot(self, ok=True):
        self.revision += 1
        return dict(self.cfg, instance=self.instance, revision=self.revision, **self.power_status,
            automatic_off=self.power.reason, version='2.5.0', backend_ready=True, ok=ok, configured=bool(self.cfg['address']),
            connection_state=self.stage, scanning=self.scanning, devices=self.devices,
            test_success=self.test_success, theme=self.theme, roles=self.roles,
            hex=self.colour, message=self.message, sent_count=self.sent_count,
            theme_latency_ms=self.theme_latency_ms, last_error=self.last_error,
            keepalive_seconds=KEEPALIVE_SECONDS, keepalive_count=self.keepalive_count,
            last_keepalive=self.last_keepalive, connection_count=self.connection_count,
            disconnect_count=getattr(self.radio, 'disconnect_count', 0),
            connect_failure_count=getattr(self.radio, 'connect_failure_count', 0),
            connected_since=self.connected_at,
            role=self.cycle.role if self.cfg.get('mode') == 'cycle' and self.cycle.role else self.cfg['role'])

    def publish(self, message=None, throttle=False):
        if message is not None:
            self.message = message
        if throttle and time.monotonic() - self.published_at < 0.5:
            return
        self.published_at = time.monotonic()
        self.write_json(STATE / 'status.json', self.snapshot())

    def theme_changed(self):
        try:
            self.theme, self.roles, _ = self.selected(self.cfg)
            if self.cfg['follow'] and self.cfg['setup_complete']:
                self.dirty = True
                self.generation += 1
                self.triggered_at = time.monotonic()
                self.wake.set()
            self.publish()
        except (OSError, ValueError):
            self.publish('Waiting for the new theme palette…')

    async def scan(self):
        try:
            self.devices = await discover()
            self.publish('Choose your light.' if self.devices else 'No RGB1 found. Check the setup steps and try again.')
        except Exception:
            self.publish('Could not search. Check Bluetooth is switched on.')
        finally:
            self.scanning = False
            self.publish()

    def command(self, action, value=None):
        from light_commands import command
        return command(self, action, value)
