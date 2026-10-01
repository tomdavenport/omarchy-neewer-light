"""One persistent, explicitly selected RGB1 connection."""
import asyncio
import logging
from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from dbus_fast import BusType, Message
from dbus_fast.aio import MessageBus
from light_config import packet, rgb1_name

WRITE = '69400002-b5a3-f393-e0a9-e50e24dcca99'
NOTIFY = '69400003-b5a3-f393-e0a9-e50e24dcca99'


async def known_device(address):
    path = '/org/bluez/hci0/dev_' + address.replace(':', '_')
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        reply = await bus.call(Message(destination='org.bluez', path=path,
            interface='org.freedesktop.DBus.Properties', member='GetAll',
            signature='s', body=['org.bluez.Device1']))
        if not reply.error_name:
            props = {key: value.value for key, value in reply.body[0].items()}
            if props.get('Address') == address:
                return BLEDevice(address, props.get('Name'), {'path': path, 'props': props})
    finally:
        bus.disconnect()
    return await BleakScanner.find_device_by_address(address, timeout=6)


async def discover():
    found = await BleakScanner.discover(timeout=6, return_adv=True)
    return sorted([
        dict(address=device.address.upper(), label='RGB1 · ' + device.address.replace(':', '')[-4:],
             rssi=advert.rssi)
        for device, advert in found.values() if rgb1_name(device.name or advert.local_name)
    ], key=lambda item: item['rssi'], reverse=True)


class Radio:
    def __init__(self, changed):
        self.client = None
        self.address = ''
        self.characteristic = None
        self.changed = changed
        self.disconnect_count = 0
        self.connect_failure_count = 0
        self.ready = False
        self.notifications = 0

    @property
    def connected(self):
        return bool(self.client and self.client.is_connected)

    def lost(self, client):
        if client is self.client:
            if self.ready:
                self.disconnect_count += 1
                logging.warning('RGB1 connection lost (drop %s)', self.disconnect_count)
            self.ready = False
            self.changed()

    def notified(self, characteristic, data):
        self.notifications += 1
        logging.info('RGB1 notification %s', bytes(data).hex())

    async def disconnect(self):
        client, self.client = self.client, None
        self.ready = False
        self.characteristic = None
        if client:
            try:
                await asyncio.wait_for(client.disconnect(), 5)
            except Exception:
                pass

    async def connect(self, cfg):
        if self.connected and self.address == cfg['address']:
            return
        await self.disconnect()
        device = await known_device(cfg['address'])
        if not device or not rgb1_name(device.name):
            raise RuntimeError('Switch your RGB1 on nearby, then try again.')
        self.address = cfg['address']
        self.client = BleakClient(device, disconnected_callback=self.lost, timeout=18)
        try:
            await self.client.connect()
            self.characteristic = self.client.services.get_characteristic(WRITE)
            if not self.characteristic or 'write-without-response' not in self.characteristic.properties:
                raise RuntimeError('This light does not offer RGB1 controls.')
            notify = self.client.services.get_characteristic(NOTIFY)
            if notify and any(prop in notify.properties for prop in ('notify', 'indicate')):
                await asyncio.wait_for(self.client.start_notify(notify, self.notified), 5)
                logging.info('RGB1 notifications enabled')
            self.ready = True
        except BaseException as error:
            if isinstance(error, Exception):
                self.connect_failure_count += 1
            await self.disconnect()
            raise

    async def write(self, cfg, action, colour):
        if not self.connected:
            raise ConnectionError('Light disconnected.')
        async def emit(mode):
            await asyncio.wait_for(self.client.write_gatt_char(
                self.characteristic, packet(cfg, mode, colour), response=False), 3)
        if action in ('on', 'off', 'test'):
            await emit('off' if action == 'off' else 'on')
            if action == 'off':
                return
            await asyncio.sleep(0.05)
        await emit('theme')
