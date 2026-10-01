"""Bounded logind shutdown delay: release immediately after the off attempt."""
import asyncio
import logging
import os
from dbus_fast import BusType, Message, MessageType
from dbus_fast.aio import MessageBus

DEST = 'org.freedesktop.login1'
PATH = '/org/freedesktop/login1'
IFACE = DEST + '.Manager'


class ShutdownWatch:
    def __init__(self, service):
        self.service, self.bus, self.fd = service, None, None
        self.changed = asyncio.Event()
        self.preparing = None
        self.timeout = 1.5
        self.owner = None

    def release(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def status(self, value):
        if self.service.power_status.get('shutdown_monitor') == value:
            return
        self.service.power_status['shutdown_monitor'] = value
        self.service.publish()

    async def call(self, **args):
        reply = await asyncio.wait_for(self.bus.call(Message(**args)), 2)
        if reply.error_name:
            raise RuntimeError(reply.error_name)
        return reply

    async def arm(self):
        reply = await self.call(destination=DEST, path=PATH, interface=IFACE,
            member='Inhibit', signature='ssss',
            body=['shutdown', 'NEEWER Light', 'Turn off the RGB1 before shutdown', 'delay'])
        if not reply.unix_fds:
            raise RuntimeError('No shutdown delay descriptor')
        self.fd = reply.unix_fds[reply.body[0]]
        os.set_inheritable(self.fd, False)
        if self.service.power.shutting_down or not self.service.cfg['off_on_shutdown']:
            self.release()
            return
        limit = await self.call(destination=DEST, path=PATH, interface='org.freedesktop.DBus.Properties',
            member='Get', signature='ss', body=[IFACE, 'InhibitDelayMaxUSec'])
        self.timeout = min(1.5, max(0.05, limit.body[0].value / 1e6 - 0.2))
        if self.service.power.shutting_down or not self.service.cfg['off_on_shutdown']:
            self.release()
        else:
            self.status('ready')

    async def prepare(self, active):
        try:
            await self.service.power.shutdown(active, self.timeout)
        except (ConnectionError, TimeoutError) as error:
            logging.warning('Shutdown light-off was not confirmed: %s', error or 'deadline reached')
        finally:
            self.release()
            self.changed.set()

    def signal(self, message):
        if (message.message_type == MessageType.SIGNAL and message.sender == self.owner and message.path == PATH
                and message.interface == IFACE and message.member == 'PrepareForShutdown'
                and len(message.body) == 1 and isinstance(message.body[0], bool)):
            if self.preparing and not self.preparing.done():
                self.preparing.cancel()
            self.preparing = asyncio.create_task(self.prepare(message.body[0]))

    async def run(self):
        while True:
            try:
                self.bus = await MessageBus(bus_type=BusType.SYSTEM, negotiate_unix_fd=True).connect()
                owner = await self.call(destination='org.freedesktop.DBus', path='/org/freedesktop/DBus',
                    interface='org.freedesktop.DBus', member='GetNameOwner', signature='s', body=[DEST])
                self.owner = owner.body[0]
                await self.call(destination='org.freedesktop.DBus', path='/org/freedesktop/DBus',
                    interface='org.freedesktop.DBus', member='AddMatch', signature='s',
                    body=[f"type='signal',sender='{DEST}',interface='{IFACE}',member='PrepareForShutdown',path='{PATH}'"])
                self.bus.add_message_handler(self.signal)
                preparing = await self.call(destination=DEST, path=PATH, interface='org.freedesktop.DBus.Properties',
                    member='Get', signature='ss', body=[IFACE, 'PreparingForShutdown'])
                if preparing.body[0].value:
                    self.preparing = asyncio.create_task(self.prepare(True))
                while self.bus.connected:
                    self.changed.clear()
                    enabled = self.service.cfg['off_on_shutdown']
                    if enabled and self.fd is None and not self.service.power.shutting_down:
                        await self.arm()
                    elif not enabled or self.service.power.shutting_down:
                        self.release()
                        self.status('disabled')
                    try:
                        await asyncio.wait_for(self.changed.wait(), 5)
                    except TimeoutError:
                        pass
            except Exception as error:
                self.status('unavailable')
                logging.warning('Shutdown notifications unavailable: %s', error)
            finally:
                self.release()
                if self.preparing:
                    self.preparing.cancel()
                    await asyncio.gather(self.preparing, return_exceptions=True)
                if self.bus:
                    self.bus.disconnect()
            await asyncio.sleep(5)
