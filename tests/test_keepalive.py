import asyncio
import unittest
from unittest.mock import patch
import light_service as module
import test_service as helpers


class KeepAliveTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = helpers.ServiceTests.asyncSetUp
    asyncTearDown = helpers.ServiceTests.asyncTearDown
    start = helpers.ServiceTests.start
    until = helpers.ServiceTests.until

    async def test_idle_refreshes_colour_without_power_commands_or_reconnects(self):
        with patch.object(module, 'KEEPALIVE_SECONDS', 0.03), patch.object(module, 'save') as saved:
            self.start()
            await self.until(lambda: self.service.keepalive_count >= 3)
            self.assertEqual(self.radio.connections, 1)
            self.assertEqual(saved.call_count, 1)
            self.assertTrue(all(row[1] == 'theme' for row in self.radio.writes))
            self.assertTrue(all(row[2] == '#123456' for row in self.radio.writes))

    async def test_silent_disconnect_recovers_colour_without_power_command(self):
        with patch.object(module, 'KEEPALIVE_SECONDS', 0.03):
            self.start()
            await self.until(lambda: bool(self.radio.writes))
            self.radio.connected = False
            await self.until(lambda: self.radio.connections == 2 and len(self.radio.writes) >= 2)
            self.assertEqual(self.radio.writes[-1][1], 'theme')

    async def test_explicit_off_stops_all_keep_on_writes(self):
        with patch.object(module, 'KEEPALIVE_SECONDS', 0.02):
            self.start()
            await self.until(lambda: bool(self.radio.writes))
            self.service.command('off')
            await self.until(lambda: self.radio.writes[-1][1] == 'off')
            count = len(self.radio.writes)
            self.radio.connected = False
            self.service.wake.set()
            await self.until(lambda: self.radio.connections == 2)
            await asyncio.sleep(0.075)
            self.assertEqual(len(self.radio.writes), count)

    async def test_follow_off_releases_link_and_stops_refreshes(self):
        with patch.object(module, 'KEEPALIVE_SECONDS', 0.02):
            self.start()
            await self.until(lambda: bool(self.radio.writes))
            self.service.command('follow', 'off')
            await self.until(lambda: not self.radio.connected)
            count = len(self.radio.writes)
            await asyncio.sleep(0.075)
            self.assertEqual(len(self.radio.writes), count)

    async def test_failed_refresh_is_not_an_explicit_on_after_follow_off(self):
        with patch.object(module, 'KEEPALIVE_SECONDS', 0.02), \
             patch.object(module, 'RETRY_SECONDS', 0.05):
            self.start()
            await self.until(lambda: bool(self.radio.writes))
            async def fail(*args):
                raise ConnectionError('refresh failed')
            self.radio.write = fail
            await self.until(lambda: self.service.last_error == 'refresh failed')
            self.service.command('follow', 'off')
            await self.until(lambda: self.service.message == 'Theme following is off.')
            self.assertIsNone(self.service.pending_power)
            self.assertEqual(self.radio.connections, 1)

    async def test_off_during_refresh_wins_and_stays_off(self):
        with patch.object(module, 'KEEPALIVE_SECONDS', 0.02):
            self.start()
            await self.until(lambda: bool(self.radio.writes))
            self.radio.write_gate = asyncio.Event()
            await self.until(lambda: self.radio.started == 2)
            self.service.command('off')
            self.radio.write_gate.set()
            await self.until(lambda: self.radio.writes[-1][1] == 'off')
            count = len(self.radio.writes)
            await asyncio.sleep(0.075)
            self.assertEqual(len(self.radio.writes), count)


if __name__ == '__main__':
    unittest.main()
