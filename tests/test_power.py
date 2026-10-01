"""Lifecycle tests use a simulated radio; they never lock or shut down the host."""
import asyncio
import unittest
import test_service as helpers


class PowerTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = helpers.ServiceTests.asyncSetUp
    asyncTearDown = helpers.ServiceTests.asyncTearDown
    start = helpers.ServiceTests.start
    until = helpers.ServiceTests.until

    async def warm(self):
        self.service.cfg.update(off_when_locked=True, off_on_shutdown=True)
        self.start()
        await self.until(lambda: bool(self.radio.writes))

    async def lock(self):
        self.service.power.lock_changed(True)
        await self.until(lambda: self.radio.writes[-1][1] == 'off')

    async def test_lock_holds_off_and_unlock_restores_saved_brightness(self):
        await self.warm()
        await self.lock()
        self.assertEqual(self.service.cfg['last_requested_power'], 'on')
        self.assertTrue(self.service.cfg['auto_off_active'])
        count = len(self.radio.writes)
        self.service.theme_changed()
        await asyncio.sleep(0.07)
        self.assertEqual(len(self.radio.writes), count)
        self.service.power.lock_changed(False)
        await self.until(lambda: self.radio.writes[-1][1] == 'on')
        self.assertEqual(self.radio.writes[-1][3], 20)
        self.assertNotIn('auto_off_active', self.service.cfg)

    async def test_manual_off_while_locked_is_never_restored(self):
        await self.warm()
        await self.lock()
        self.service.command('off')
        count = len(self.radio.writes)
        self.service.power.lock_changed(False)
        await asyncio.sleep(0.07)
        self.assertEqual(len(self.radio.writes), count)
        self.assertEqual(self.service.cfg['last_requested_power'], 'off')

    async def test_preview_while_locked_waits_until_unlock(self):
        await self.warm()
        await self.lock()
        count = len(self.radio.writes)
        self.service.command('preview', 'alternate')
        await asyncio.sleep(0.07)
        self.assertEqual(len(self.radio.writes), count)
        self.service.power.lock_changed(False)
        await self.until(lambda: self.radio.writes[-1][1:] == ('on', '#eeeeee', 20))

    async def test_unlock_during_off_write_restores_after_that_write(self):
        await self.warm()
        self.radio.write_gate = asyncio.Event()
        self.service.power.lock_changed(True)
        await self.until(lambda: self.radio.started == 2)
        self.service.power.lock_changed(False)
        self.radio.write_gate.set()
        await self.until(lambda: len(self.radio.writes) == 3)
        self.assertEqual([row[1] for row in self.radio.writes], ['theme', 'off', 'on'])

    async def test_reconnect_while_locked_reasserts_off(self):
        await self.warm()
        await self.lock()
        self.radio.connected = False
        self.service.wake.set()
        await self.until(lambda: self.radio.connections == 2)
        self.assertEqual(self.radio.writes[-1][1], 'off')
        self.assertFalse(any(row[1] == 'on' for row in self.radio.writes))

    async def test_shutdown_off_keeps_desired_on_for_next_login(self):
        await self.warm()
        await self.service.power.shutdown(True, timeout=0.2)
        self.assertEqual(self.radio.writes[-1][1], 'off')
        self.assertEqual(self.service.cfg['last_requested_power'], 'on')
        self.assertTrue(self.service.cfg['auto_off_active'])

    async def test_shutdown_write_deadline_is_bounded(self):
        await self.warm()
        self.radio.write_gate = asyncio.Event()
        with self.assertRaises(TimeoutError):
            await self.service.power.shutdown(True, timeout=0.03)
        self.assertFalse(self.service.power.auto_off_sent)
        self.assertNotIn('auto_off_active', self.service.cfg)

    async def test_disabled_power_options_do_not_send_off(self):
        self.start()
        await self.until(lambda: bool(self.radio.writes))
        self.service.power.lock_changed(True)
        await self.service.power.shutdown(True)
        await asyncio.sleep(0.03)
        self.assertEqual([row[1] for row in self.radio.writes], ['theme'])

    async def test_disabling_lock_option_restores_only_auto_off(self):
        await self.warm()
        await self.lock()
        self.service.command('lock-off', 'off')
        await self.until(lambda: self.radio.writes[-1][1] == 'on')

    async def test_failed_off_does_not_turn_on_at_unlock(self):
        await self.warm()
        async def fail(*args):
            raise ConnectionError('offline')
        self.radio.write = fail
        self.service.power.lock_changed(True)
        await self.until(lambda: self.service.stage == 'offline')
        self.service.power.lock_changed(False)
        self.assertNotEqual(self.service.pending_power, 'on')

    async def test_saved_automatic_off_restores_on_authoritative_unlock(self):
        self.service.power.auto_off_sent = True
        self.service.cfg.update(auto_off_active=True, off_when_locked=True)
        self.service.power.lock_changed(False)
        self.start()
        await self.until(lambda: bool(self.radio.writes))
        self.assertEqual(self.radio.writes[-1][1], 'on')
