"""Connection diagnostics must distinguish failed setup from a live link dropping."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
import light_ble as module


class RadioTests(unittest.IsolatedAsyncioTestCase):
    def client(self):
        return SimpleNamespace(is_connected=True,
            services=SimpleNamespace(get_characteristic=lambda uuid:
                SimpleNamespace(properties=['write-without-response']) if uuid == module.WRITE else None),
            connect=AsyncMock(), disconnect=AsyncMock())

    async def test_failed_connection_callback_is_not_a_dropped_ready_link(self):
        changed = Mock()
        radio = module.Radio(changed)
        client = self.client()
        async def timeout():
            client.is_connected = False
            radio.lost(client)
            raise TimeoutError()
        client.connect.side_effect = timeout
        with patch.object(module, 'known_device', AsyncMock(return_value=SimpleNamespace(name='RGB1'))), \
             patch.object(module, 'rgb1_name', return_value=True), \
             patch.object(module, 'BleakClient', return_value=client):
            with self.assertRaises(TimeoutError):
                await radio.connect({'address': 'test'})
        self.assertEqual(radio.disconnect_count, 0)
        self.assertEqual(radio.connect_failure_count, 1)
        self.assertFalse(radio.connected)

    async def test_ready_link_loss_counts_once_and_wakes_recovery(self):
        changed = Mock()
        radio = module.Radio(changed)
        client = self.client()
        with patch.object(module, 'known_device', AsyncMock(return_value=SimpleNamespace(name='RGB1'))), \
             patch.object(module, 'rgb1_name', return_value=True), \
             patch.object(module, 'BleakClient', return_value=client):
            await radio.connect({'address': 'test'})
        client.is_connected = False
        radio.lost(client)
        radio.lost(client)
        self.assertEqual(radio.disconnect_count, 1)
        self.assertEqual(radio.connect_failure_count, 0)
        changed.assert_called()

    async def test_deliberate_release_does_not_count_as_a_drop(self):
        radio = module.Radio(Mock())
        client = self.client()
        radio.client, radio.ready = client, True
        client.disconnect.side_effect = lambda: radio.lost(client)
        await radio.disconnect()
        self.assertEqual(radio.disconnect_count, 0)
        self.assertFalse(radio.connected)


if __name__ == '__main__':
    unittest.main()
