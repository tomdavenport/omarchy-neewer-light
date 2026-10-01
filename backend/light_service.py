"""Event-driven state and a warm BLE link; IPC is in light_daemon.py."""
import asyncio
import logging
import time
from light_config import STATE, load, save, selected, write_json, packet
from light_ble import Radio, discover
from light_effects import PaletteCycle

KEEPALIVE_SECONDS = 5.0
RETRY_SECONDS = 2.0


class LightService:
    def __init__(self):
        self.cfg = load()
        self.cycle = PaletteCycle()
        self.wake = asyncio.Event()
        self.radio = Radio(self.wake.set)
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
        self.theme, self.roles, self.colour = selected(self.cfg)
        self.tasks = set()

    def snapshot(self, ok=True):
        return dict(self.cfg, version='2.4.0', backend_ready=True, ok=ok, configured=bool(self.cfg['address']),
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
        write_json(STATE / 'status.json', self.snapshot())

    def theme_changed(self):
        try:
            self.theme, self.roles, self.colour = selected(self.cfg)
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

    async def run(self):
        failures = 0
        while True:
            self.wake.clear()
            action, retry_power, attempt_address = None, None, self.cfg['address']
            send_started, attempt_generation, requested_colour = False, self.generation, self.dirty
            keep = self.cfg['follow'] and self.cfg['setup_complete']
            wanted = self.cfg['address'] and (keep or self.dirty or self.pending_power or self.probe_requested)
            if not wanted:
                await self.radio.disconnect()
                self.connected_at = None
                self.stage = 'offline' if self.cfg['address'] else 'unconfigured'
                self.publish('Theme following is off.' if self.cfg['address'] else 'Connect your RGB1 to get started.')
            else:
                try:
                    if not self.radio.connected or self.radio.address != self.cfg['address']:
                        self.stage, self.last_signature, self.connected_at = 'connecting', None, None
                        self.publish('Waiting for RGB1 · reconnecting automatically.' if failures
                                     else 'Connecting to your RGB1…')
                        await asyncio.wait_for(self.radio.connect(dict(self.cfg)), 26)
                        if self.radio.address != self.cfg['address']:
                            continue
                        self.connection_count += 1
                        self.connected_at = time.strftime('%Y-%m-%d %H:%M:%S')
                        self.last_activity = 0.0
                        logging.info('RGB1 connected (connection %s)', self.connection_count)
                        self.dirty |= self.cfg['follow'] and self.cfg['setup_complete']
                    keep = self.cfg['follow'] and self.cfg['setup_complete']
                    if not (keep or self.dirty or self.pending_power or self.probe_requested):
                        continue
                    self.stage, self.probe_requested = 'ready', False
                    refresh = (keep and self.cfg.get('last_requested_power') != 'off'
                               and time.monotonic() - self.last_activity >= KEEPALIVE_SECONDS)
                    action = self.pending_power or 'theme'
                    try:
                        theme, roles, _ = selected(self.cfg)
                        rendered, colour, advanced = self.cycle.render(self.cfg, roles)
                        self.dirty |= advanced
                    except (OSError, ValueError):
                        self.publish('Waiting for the new theme palette…')
                        await self.wake.wait()
                        continue
                    active = rendered
                    self.theme, self.roles, self.colour = theme, roles, colour
                    attempt_generation, requested_colour = self.generation, self.dirty
                    signature = (active['address'], packet(active, 'theme', colour))
                    should_send = self.pending_power or refresh or (self.dirty and active.get('last_requested_power') != 'off'
                        and (self.force or signature != self.last_signature))
                    self.dirty, self.force = False, False
                    if should_send:
                        retry_power, self.pending_power = self.pending_power, None
                        send_started = True
                        await self.radio.write(active, action, colour)
                        self.last_activity = time.monotonic()
                        if refresh and not retry_power:
                            self.keepalive_count += 1
                            self.last_keepalive = time.strftime('%Y-%m-%d %H:%M:%S')
                        if self.cfg['address'] == active['address']:
                            self.cfg['last_sent'] = time.strftime('%Y-%m-%d %H:%M:%S')
                            if action != 'off':
                                self.cfg.update(last_colour=colour, last_theme=theme, last_role=active['role'])
                            if action == 'test':
                                self.test_success = True
                            self.last_signature = None if action == 'off' else signature
                            self.sent_count += 1
                            if self.triggered_at is not None:
                                self.theme_latency_ms = round((time.monotonic() - self.triggered_at) * 1000, 1)
                                self.triggered_at = None
                            if retry_power or ((not refresh or requested_colour) and not advanced):
                                save(self.cfg)
                    failures, self.last_error = 0, ''
                    self.publish('Light kept off.' if self.cfg.get('last_requested_power') == 'off' else 'Keeping colour active · following theme.' if keep else 'Light updated.', throttle=advanced)
                    if not keep and not self.pending_power and not self.dirty:
                        await self.radio.disconnect()
                        self.stage, self.connected_at = 'offline', None
                        self.publish('Theme following is off.')
                except Exception as error:
                    self.last_error = str(error) or type(error).__name__
                    logging.warning('RGB1 retry after %s', self.last_error)
                    self.connected_at = None
                    await self.radio.disconnect()
                    self.stage = 'offline'
                    failures += 1
                    if send_started and attempt_generation == self.generation and attempt_address == self.cfg['address']:
                        self.dirty |= requested_colour
                        if retry_power and not self.pending_power:
                            self.pending_power = retry_power
                    self.dirty |= self.cfg['follow'] and self.cfg['setup_complete'] and self.cfg.get('last_requested_power') != 'off'
                    self.publish('Light unavailable. Leave it switched on nearby; reconnecting…')
                    if not self.cfg['follow'] and failures >= 2:
                        self.dirty, self.pending_power, self.probe_requested = False, None, False
                        self.publish('Light unavailable. Switch it on nearby and try again.')
                        await self.wake.wait()
                        continue
                    try:
                        await asyncio.wait_for(self.wake.wait(), RETRY_SECONDS)
                    except TimeoutError:
                        pass
                    continue
            if not self.wake.is_set():
                if self.cfg['follow'] and self.cfg['setup_complete']:
                    delay = max(0.01, KEEPALIVE_SECONDS - (time.monotonic() - self.last_activity))
                    if self.cfg.get('last_requested_power') == 'off':
                        delay = KEEPALIVE_SECONDS
                    effect_delay = self.cycle.wait_seconds(self.cfg)
                    if effect_delay is not None:
                        delay = min(delay, effect_delay)
                    try:
                        await asyncio.wait_for(self.wake.wait(), delay)
                    except TimeoutError:
                        pass
                else:
                    await self.wake.wait()
