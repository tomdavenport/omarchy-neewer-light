import asyncio
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from dbus_fast import Message, MessageType
from shutdown_watch import PATH, IFACE
from shutdown_watch import ShutdownWatch


class ShutdownWatchTests(unittest.IsolatedAsyncioTestCase):
    def make(self):
        power = SimpleNamespace(shutting_down=False, shutdown=AsyncMock())
        service = SimpleNamespace(cfg={'off_on_shutdown':True}, power=power,
                                  power_status={}, publish=lambda: None)
        return ShutdownWatch(service)

    async def test_off_attempt_releases_inhibitor_even_on_failure(self):
        for error in (None, TimeoutError(), ConnectionError('offline')):
            watcher = self.make()
            watcher.service.power.shutdown.side_effect = error
            read, write = os.pipe()
            os.close(write)
            watcher.fd = read
            await watcher.prepare(True)
            self.assertIsNone(watcher.fd)
            with self.assertRaises(OSError):
                os.fstat(read)

    async def test_shutdown_arriving_during_inhibit_acquisition_closes_late_fd(self):
        watcher = self.make()
        read, write = os.pipe()
        os.close(write)
        gate = asyncio.Event()
        async def call(**args):
            await gate.wait()
            return SimpleNamespace(unix_fds=[read], body=[0])
        watcher.call = call
        task = asyncio.create_task(watcher.arm())
        await asyncio.sleep(0)
        watcher.service.power.shutting_down = True
        gate.set()
        await task
        self.assertIsNone(watcher.fd)
        with self.assertRaises(OSError):
            os.fstat(read)

    async def test_system_delay_limit_bounds_internal_deadline(self):
        watcher = self.make()
        read, write = os.pipe()
        os.close(write)
        watcher.call = AsyncMock(side_effect=[SimpleNamespace(unix_fds=[read],body=[0]),
            SimpleNamespace(body=[SimpleNamespace(value=700000)])])
        try:
            await watcher.arm()
            self.assertAlmostEqual(watcher.timeout, 0.5)
            self.assertFalse(os.get_inheritable(read))
        finally:
            watcher.release()

    async def test_shutdown_during_delay_limit_query_also_closes_fd(self):
        watcher = self.make()
        read, write = os.pipe()
        os.close(write)
        gate = asyncio.Event()
        async def call(**args):
            if args['member'] == 'Inhibit':
                return SimpleNamespace(unix_fds=[read], body=[0])
            await gate.wait()
            return SimpleNamespace(body=[SimpleNamespace(value=5000000)])
        watcher.call = call
        task = asyncio.create_task(watcher.arm())
        await asyncio.sleep(0)
        self.assertEqual(watcher.fd, read)
        watcher.service.power.shutting_down = True
        gate.set()
        await task
        self.assertIsNone(watcher.fd)
        with self.assertRaises(OSError):
            os.fstat(read)

    async def test_only_logind_owner_can_deliver_shutdown_signal(self):
        watcher = self.make()
        watcher.owner = ':1.10'
        for sender in (':1.99', ':1.10'):
            watcher.signal(Message(message_type=MessageType.SIGNAL, sender=sender, path=PATH,
                interface=IFACE, member='PrepareForShutdown', signature='b', body=[True]))
            await asyncio.sleep(0)
            self.assertEqual(watcher.service.power.shutdown.call_count, int(sender == ':1.10'))
        await watcher.preparing
