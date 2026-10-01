"""Automatic power never changes the user's explicit On/Off preference."""
import asyncio


class PowerPolicy:
    def __init__(self, service):
        self.service = service
        self.locked, self.shutting_down, self.blocked = None, False, False
        self.auto_off_sent = bool(service.cfg.get('auto_off_active'))
        self.off_done = asyncio.Event()

    @property
    def reason(self):
        cfg = self.service.cfg
        if self.shutting_down and cfg['off_on_shutdown']:
            return 'shutdown'
        return 'locked' if self.locked and cfg['off_when_locked'] else ''

    def effective(self):
        cfg = dict(self.service.cfg)
        if self.blocked:
            cfg['last_requested_power'] = 'off'
        return cfg

    def reconcile(self):
        service = self.service
        if not service.cfg['address'] or not service.cfg['setup_complete']:
            self.blocked = False
            return
        service.generation += 1
        previous, self.blocked = self.blocked, bool(self.reason)
        if self.blocked:
            service.transition.cancel(service.theme, service.roles)
            service.pending_power = None if self.auto_off_sent else 'off'
            service.dirty, service.force = False, False
        elif previous or (self.auto_off_sent and (self.locked is False or not service.cfg['off_when_locked'])):
            if self.auto_off_sent and service.cfg.get('last_requested_power') != 'off':
                service.pending_power, service.dirty = 'on', True
                service.cycle.reset(service.cfg, preserve=True)
            elif service.pending_power == 'off' and service.cfg.get('last_requested_power') != 'off':
                service.pending_power = None
        service.wake.set()

    def lock_changed(self, locked):
        self.locked = locked
        self.reconcile()
        self.service.publish()

    def reconnected(self):
        if self.blocked:
            self.auto_off_sent = False
            self.reconcile()

    def written(self, action, automatic):
        service = self.service
        if action == 'off':
            self.off_done.set()
            if automatic:
                self.auto_off_sent = service.cfg['auto_off_active'] = True
                if not self.blocked:  # Unlock may arrive during the BLE write.
                    self.reconcile()
        elif action in ('on', 'test'):
            self.auto_off_sent = False
            service.cfg.pop('auto_off_active', None)

    async def shutdown(self, preparing, timeout=1.5):
        self.shutting_down = preparing
        self.off_done.clear()
        self.reconcile()
        if not preparing or not self.service.cfg['off_on_shutdown']:
            return
        if self.auto_off_sent:
            return
        if not self.service.radio.connected:
            raise ConnectionError('Light unavailable during shutdown; off could not be confirmed.')
        await asyncio.wait_for(self.off_done.wait(), timeout)
