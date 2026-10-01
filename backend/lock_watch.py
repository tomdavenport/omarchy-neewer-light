"""Minimal receive-only Hyprland lock-notify client; no windows or input APIs.

Wire schema: hyprwm/hyprland-protocols/protocols/hyprland-lock-notify-v1.xml.
Only wl_registry, wl_callback and the lock notifier are bound. No native deps.
"""
import asyncio
import logging
import os
from pathlib import Path
import struct

INTERFACE = 'hyprland_lock_notifier_v1'


def message(object_id, opcode, payload=b''):
    return struct.pack('=II', object_id, ((8 + len(payload)) << 16) | opcode) + payload


def string(value):
    data = value.encode() + b'\0'
    return struct.pack('=I', len(data)) + data + b'\0' * (-len(data) % 4)


class LockWatch:
    def __init__(self, service):
        self.service, self.writer = service, None
        self.changed, self.ready = asyncio.Event(), asyncio.Event()

    def update(self):
        if not self.service.cfg['off_when_locked'] and self.writer:
            self.writer.close()
        self.changed.set()

    def status(self, value):
        self.service.power_status['lock_monitor'] = value
        self.service.publish()

    async def listen(self, path):
        reader, self.writer = await asyncio.wait_for(asyncio.open_unix_connection(path), 2)
        self.service.power.locked = None
        bound = None
        initialized = False
        self.writer.write(message(1, 1, struct.pack('=I', 2)))  # get_registry
        self.writer.write(message(1, 0, struct.pack('=I', 3)))  # sync registry
        await self.writer.drain()
        while True:
            header = await asyncio.wait_for(reader.readexactly(8), None if initialized else 3)
            obj, size_opcode = struct.unpack('=II', header)
            size, opcode = size_opcode >> 16, size_opcode & 0xffff
            if size < 8 or size % 4:
                raise ValueError('Invalid Wayland event size')
            body = await asyncio.wait_for(reader.readexactly(size - 8), 3)
            if obj == 1 and opcode == 0:
                raise ConnectionError('Wayland rejected lock notifications')
            if obj == 2 and opcode == 0:
                if len(body) < 12:
                    raise ValueError('Invalid registry event')
                name, length = struct.unpack_from('=II', body)
                end = 8 + ((length + 3) & ~3)
                if length < 1 or end + 4 != len(body):
                    raise ValueError('Invalid registry interface')
                interface = body[8:8 + length - 1].decode()
                version, = struct.unpack_from('=I', body, end)
                if interface == INTERFACE and version >= 1 and bound is None:
                    bound = name
                    self.writer.write(message(2, 0, struct.pack('=I', name) + string(INTERFACE) + struct.pack('=II', 1, 4)))
                    self.writer.write(message(4, 1, struct.pack('=I', 5)))
                    self.writer.write(message(1, 0, struct.pack('=I', 6)))
                    await self.writer.drain()
            elif obj == 2 and opcode == 1 and body == struct.pack('=I', bound or 0):
                raise ConnectionError('Lock notification protocol removed')
            elif obj == 3 and opcode == 0 and bound is None:
                raise RuntimeError('This compositor does not support lock notifications')
            elif obj == 5 and opcode in (0, 1) and not body:
                self.service.power.lock_changed(opcode == 0)
            elif obj == 6 and opcode == 0:
                initialized = True
                if self.service.power.locked is None:
                    self.service.power.lock_changed(False)
                self.status('ready')
                self.ready.set()

    async def run(self):
        while True:
            self.changed.clear()
            if not self.service.cfg['off_when_locked']:
                self.status('disabled')
                self.ready.set()
                await self.changed.wait()
                continue
            try:
                display = os.environ.get('WAYLAND_DISPLAY')
                if not display:
                    raise RuntimeError('Wayland session is unavailable')
                path = Path(display) if display.startswith('/') else Path(os.environ['XDG_RUNTIME_DIR']) / display
                await self.listen(str(path))
            except (OSError, ValueError, RuntimeError, asyncio.IncompleteReadError) as error:
                logging.warning('Lock notifications unavailable: %s', error)
                self.status('unavailable')
                self.ready.set()
            finally:
                if self.writer:
                    self.writer.close()
                    try:
                        await self.writer.wait_closed()
                    except OSError:
                        pass
                    self.writer = None
            try:
                await asyncio.wait_for(self.changed.wait(), 5)
            except TimeoutError:
                pass
