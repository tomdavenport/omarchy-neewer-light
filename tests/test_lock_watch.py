"""A disposable Unix socket stands in for Wayland; no host session access."""
import asyncio
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from lock_watch import LockWatch, INTERFACE, message, string


class LockWatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_wire_handshake_and_lock_events_only(self):
        events, requests = [], []
        def changed(value):
            events.append(value)
            policy.locked = value
        policy = SimpleNamespace(locked=None, lock_changed=changed)
        service = SimpleNamespace(power=policy, power_status={}, publish=lambda: None)
        watcher = LockWatch(service)
        finished = asyncio.Event()
        async def server(reader, writer):
            try:
                async def request():
                    obj, packed = struct.unpack('=II', await reader.readexactly(8))
                    body = await reader.readexactly((packed >> 16) - 8)
                    requests.append((obj, packed & 0xffff, body))
                await request()
                await request()
                writer.write(message(2, 0, struct.pack('=I', 10) + string(INTERFACE) + struct.pack('=I', 1)))
                writer.write(message(3, 0, struct.pack('=I', 99)))
                await writer.drain()
                for _ in range(3):
                    await request()
                # The session starts locked: no spurious initial unlock.
                writer.write(message(5, 0))
                writer.write(message(6, 0, struct.pack('=I', 100)))
                writer.write(message(5, 1))
                await writer.drain()
                await finished.wait()
            finally:
                writer.close()
                await writer.wait_closed()
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'fake-wayland')
            listener = await asyncio.start_unix_server(server, path=path)
            task = asyncio.create_task(watcher.listen(path))
            try:
                async with asyncio.timeout(1):
                    while events != [True, False]:
                        await asyncio.sleep(0.002)
                self.assertEqual(service.power_status['lock_monitor'], 'ready')
                self.assertEqual([(r[0], r[1]) for r in requests], [(1,1),(1,0),(2,0),(4,1),(1,0)])
                self.assertEqual(requests[2][2], struct.pack('=I', 10) + string(INTERFACE) + struct.pack('=II', 1, 4))
            finally:
                finished.set()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                if watcher.writer:
                    watcher.writer.close()
                    await watcher.writer.wait_closed()
                listener.close()
                await listener.wait_closed()

    async def test_missing_protocol_reports_failure_instead_of_inventing_unlock(self):
        events = []
        service = SimpleNamespace(power=SimpleNamespace(locked=None, lock_changed=events.append))
        watcher = LockWatch(service)
        async def server(reader, writer):
            await reader.readexactly(24)
            writer.write(message(3, 0, struct.pack('=I', 1)))
            await writer.drain()
            writer.close()
            await writer.wait_closed()
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'fake-wayland')
            listener = await asyncio.start_unix_server(server, path=path)
            try:
                with self.assertRaisesRegex(RuntimeError, 'does not support'):
                    await watcher.listen(path)
                self.assertEqual(events, [])
            finally:
                watcher.writer.close()
                await watcher.writer.wait_closed()
                listener.close()
                await listener.wait_closed()
