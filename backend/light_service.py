"""Serial BLE writer; commands, presentation and lifecycle state are separate."""
import asyncio
import logging
import time
from light_config import load, save, selected, write_json, packet
from light_ble import Radio
from light_transition import FADE_DURATIONS
from light_state import LightState

KEEPALIVE_SECONDS = 5.0
RETRY_SECONDS = 2.0


class LightService(LightState):
    def __init__(self):
        super().__init__(load=load, radio=Radio, selected=selected, write_json=write_json)

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
                        self.theme, self.roles, _ = selected(self.cfg)
                        self.power.reconnected()
                        self.dirty |= self.cfg['follow'] and self.cfg['setup_complete']
                    keep = self.cfg['follow'] and self.cfg['setup_complete']
                    if not (keep or self.dirty or self.pending_power or self.probe_requested):
                        continue
                    self.stage, self.probe_requested = 'ready', False
                    effective = self.power.effective()
                    refresh = (keep and effective.get('last_requested_power') != 'off'
                               and time.monotonic() - self.last_activity >= KEEPALIVE_SECONDS)
                    action = self.pending_power or 'theme'
                    try:
                        theme, roles = self.theme, self.roles
                        rendered, colour, advanced = self.cycle.render(effective, roles)
                        colour, fading = self.transition.render(theme, roles, colour, self.cfg.get('last_colour'),
                            bool(keep and self.last_signature and not self.pending_power
                                 and effective.get('last_requested_power') != 'off'),
                            FADE_DURATIONS[self.cfg['theme_fade']])
                        advanced |= fading
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
                        automatic = self.power.blocked and action == 'off'
                        await self.radio.write(active, action, colour)
                        self.last_activity = time.monotonic()
                        if refresh and not retry_power:
                            self.keepalive_count += 1
                            self.last_keepalive = time.strftime('%Y-%m-%d %H:%M:%S')
                        if self.cfg['address'] == active['address']:
                            self.power.written(action, automatic)
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
                    self.publish('Light off while ' + self.power.reason + '.' if self.power.blocked else
                                 'Light kept off.' if self.cfg.get('last_requested_power') == 'off' else
                                 'Following theme · cycling colours.' if keep and self.cfg['mode'] == 'cycle' else
                                 'Following theme · holding colour.' if keep else 'Light updated.', throttle=advanced)
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
                    if self.power.blocked or self.cfg.get('last_requested_power') == 'off':
                        delay = KEEPALIVE_SECONDS
                    effect_delay = self.transition.wait_seconds(self.cycle.wait_seconds(self.power.effective()))
                    if effect_delay is not None:
                        delay = min(delay, effect_delay)
                    try:
                        await asyncio.wait_for(self.wake.wait(), delay)
                    except TimeoutError:
                        pass
                else:
                    await self.wake.wait()
